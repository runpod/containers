#!/usr/bin/env bash
# fabric.sh — cluster-fabric preflight library, baked into the ray-cluster
# image and sourced by /ray-entrypoint.sh.
#
# Ported from runpod/host pkg/cluster/fabric.sh. In the Slurm arm the daemon
# still bind-mounts this library at /fabric.sh; Ray cluster pods now run only on
# this designated image, so the image owns its own copy (see the Ray init
# refactor: "Ray owns the equivalent preflight in its designated image now").
# Keep this in sync with the host copy — a drift means the two cluster arms
# self-heal the NCCL fabric differently.
#
# Contract:
#   in:   daemon-injected env — NODE_ADDR (own overlay IP, CIDR-suffixed),
#         PRIMARY_ADDR (first member's overlay IP), NCCL_SOCKET_IFNAME /
#         GLOO_SOCKET_IFNAME / NCCL_IB_DISABLE / NCCL_IB_HCA / NCCL_IB_GID_INDEX
#         (only when set), plus RAY_NCCL_GDR_LEVEL / NCCL_* overrides.
#   out:  verified/filled NCCL_* + GLOO_* exports, and an env-record file.
#
# Callers set FABRIC_NODE_IP (or let fabric_node_ip derive it) and call, in
# order: fabric_self_heal_ifname, fabric_defaults, fabric_write_env_record PATH.

# Effective overlay IP of this pod: own NODE_ADDR (CIDR stripped), else PRIMARY.
fabric_node_ip() {
    local ip=${NODE_ADDR:-$PRIMARY_ADDR}
    printf '%s' "${ip%%/*}"
    return 0
}

# The daemon pins NCCL_SOCKET_IFNAME from a link-count guess (ens1[,ens2...]).
# Base-image interface naming varies (ens vs enp vs eth), and a wrong value
# means NCCL bootstraps over the wrong NIC: silent hang or order-of-magnitude
# collectives slowdown. Self-heal against ground truth — the interface that
# actually owns this pod's overlay IP. Route lookups are accepted only when the
# kernel would source the packet FROM our overlay IP — otherwise the answer is
# the public default-route NIC, exactly the pin we must never make.
fabric_self_heal_ifname() {
    local node_ip=${FABRIC_NODE_IP:-$(fabric_node_ip)}
    if ! command -v ip > /dev/null 2>&1; then
        echo "note: 'ip' tool unavailable; trusting daemon NCCL_SOCKET_IFNAME='${NCCL_SOCKET_IFNAME:-<unset>}'"
        return
    fi
    case "$node_ip" in
        127.* | 169.254.* | "")
            echo "note: overlay IP '$node_ip' is loopback/link-local/empty; skipping fabric iface verification"
            return
            ;;
        *)
            ;;
    esac
    local dev srcroute routedev
    dev=$(ip -o -4 addr show to "$node_ip" 2> /dev/null | awk 'NR==1{print $2}')
    if [[ -z "$dev" ]]; then
        srcroute=$(ip -o -4 route get "$node_ip" 2> /dev/null | head -n1)
        routedev=$(printf '%s' "$srcroute" | sed -n 's/.*dev \([^ ]*\).*/\1/p')
        # Route lookups against our own (local) address answer "dev lo" with a
        # matching src — that's loopback bookkeeping, not the overlay iface.
        if [[ -n "$routedev" && "$routedev" != "lo" ]] && printf '%s' "$srcroute" | grep -q "src $node_ip\b"; then
            dev=$routedev
        fi
    fi
    if [[ -z "$dev" ]]; then
        echo "warn: could not map overlay IP $node_ip to an interface; leaving NCCL_SOCKET_IFNAME='${NCCL_SOCKET_IFNAME:-<unset>}' as-is"
        return
    fi
    if [[ -z "${NCCL_SOCKET_IFNAME:-}" ]]; then
        export NCCL_SOCKET_IFNAME="$dev"
        echo "derived NCCL_SOCKET_IFNAME=$dev from overlay IP"
    elif [[ ,$NCCL_SOCKET_IFNAME, != *,"$dev",* ]]; then
        echo "warn: NCCL_SOCKET_IFNAME='$NCCL_SOCKET_IFNAME' does not carry overlay IP $node_ip (iface $dev); overriding"
        # A multi-rail daemon pin (e.g. 'ens1,ens2') collapses to the single
        # verified carrier — correct fabric beats silent bandwidth halving.
        # Replace (not append) stays deliberate; the dropped rails are logged.
        if [[ "$NCCL_SOCKET_IFNAME" == *,* ]]; then
            echo "note: multi-rail override collapses '$NCCL_SOCKET_IFNAME' to verified iface $dev; other rails dropped"
        fi
        # Gloo rides the same fabric and the daemon pins it from the same
        # guess — mirror the override when unset or still equal to the old value.
        case "${GLOO_SOCKET_IFNAME:-}" in
            "" | "$NCCL_SOCKET_IFNAME")
                export GLOO_SOCKET_IFNAME="$dev"
                echo "mirrored GLOO_SOCKET_IFNAME=$dev"
                ;;
            *)
                ;;
        esac
        export NCCL_SOCKET_IFNAME="$dev"
    else
        echo "fabric iface verified: $dev carries $node_ip"
    fi
}

# Deterministic defaults for the gaps the daemon leaves. Explicit daemon-set
# values always win.
fabric_defaults() {
    export NCCL_SOCKET_FAMILY=${NCCL_SOCKET_FAMILY:-AF_INET}
    export NCCL_DEBUG=${NCCL_DEBUG:-WARN}

    # Gloo's control plane rides the same fabric; mirror the verified iface.
    if [[ -z "${GLOO_SOCKET_IFNAME:-}" && -n "${NCCL_SOCKET_IFNAME:-}" ]]; then
        export GLOO_SOCKET_IFNAME="$NCCL_SOCKET_IFNAME"
    fi

    # IB verbs probing wastes startup seconds on non-RDMA pods.
    # compgen -G is a shell builtin (no ls forks) and glob-matches directory
    # CONTENTS — an existing-but-empty /dev/infiniband must not enable IB.
    if [[ -z "${NCCL_IB_DISABLE:-}" ]]; then
        if compgen -G '/dev/infiniband/*' > /dev/null || compgen -G '/sys/class/infiniband/*' > /dev/null; then
            export NCCL_IB_DISABLE=0
        else
            export NCCL_IB_DISABLE=1
        fi
    fi
    if [[ "$NCCL_IB_DISABLE" = "0" && -z "${NCCL_NET_GDR_LEVEL:-}" ]]; then
        # PHB keeps DMA on the PCIe root complex without over-asserting
        # locality; tighten via RAY_NCCL_GDR_LEVEL on known-good fabrics.
        export NCCL_NET_GDR_LEVEL=${RAY_NCCL_GDR_LEVEL:-PHB}
    fi
    return 0
}

# Sourceable record of the exact fabric env the runtime started with, so
# interactive shells and workloads see the same settings without re-deriving
# them. Arg: destination path. The :- defaults keep the record complete when
# called standalone (before fabric_defaults has run).
fabric_write_env_record() {
    local dest=$1
    {
        echo "export FABRIC_NODE_IP=${FABRIC_NODE_IP:-$(fabric_node_ip)}"
        echo "export NCCL_SOCKET_IFNAME=${NCCL_SOCKET_IFNAME:-}"
        echo "export GLOO_SOCKET_IFNAME=${GLOO_SOCKET_IFNAME:-}"
        echo "export NCCL_SOCKET_FAMILY=${NCCL_SOCKET_FAMILY:-}"
        echo "export NCCL_DEBUG=${NCCL_DEBUG:-}"
        echo "export NCCL_IB_DISABLE=${NCCL_IB_DISABLE:-}"
        echo "export NCCL_IB_HCA=${NCCL_IB_HCA:-}"
        echo "export NCCL_IB_GID_INDEX=${NCCL_IB_GID_INDEX:-}"
        echo "export NCCL_NET_GDR_LEVEL=${NCCL_NET_GDR_LEVEL:-}"
    } > "$dest" 2> /dev/null || echo "note: could not write $dest"
    return 0
}
