#!/usr/bin/env bash
# ray-entrypoint.sh — brings up this node's Ray process (head or worker).
#
# Runs as the supervisord `ray-node` program (autostart + autorestart), so it
# ends in `exec ray start ... --block`: Ray stays in the foreground and
# supervisord owns its lifecycle (restart-on-crash, unified logs). If a worker's
# head is not yet reachable this script exits non-zero and supervisord retries,
# which is the registration retry loop.
#
# The daemon injects the topology env and no longer injects a launch script (see
# the Ray init refactor in runpod/host): the image owns launch. Readiness and
# liveness are observed from the HOST — the daemon polls this node's dashboard
# (:${RAY_DASHBOARD_PORT}/api/healthz, /nodes) and scrapes its Ray metrics
# (:${RAY_METRICS_PORT}) — so the ports below are a contract with the host, not
# just internal config. Do not rename them without changing pkg/rayready /
# pkg/raymetrics in runpod/host.
set -uo pipefail

log() { echo "[ray-entrypoint] $*"; }

# --- Ports (host-facing contract) ------------------------------------------- #
# 6379   GCS: workers dial PRIMARY_ADDR:RAY_GCS_PORT to register.
# 8265   Dashboard, bound 0.0.0.0 so the host reaches it on the docker bridge;
#        pkg/rayready polls /api/healthz + /nodes here.
# 8080   Ray Prometheus metrics; injected as RAY_METRICS_PORT by the daemon so
#        the pinned value is a single source of truth with pkg/raymetrics'
#        scraper. Falls back to a local default if the daemon didn't inject it.
# 52365  Dashboard agent (per-node raylet healthz), KubeRay's default; used by
#        the local liveness probe (ray-health.sh) and the Docker HEALTHCHECK.
RAY_GCS_PORT=${RAY_GCS_PORT:-6379}
RAY_DASHBOARD_PORT=${RAY_DASHBOARD_PORT:-8265}
RAY_METRICS_PORT=${RAY_METRICS_PORT:-8080}
RAY_DASHBOARD_AGENT_PORT=${RAY_DASHBOARD_AGENT_PORT:-52365}

# --- Role ------------------------------------------------------------------- #
# NODE_ROLE is RAY_HEAD / RAY_WORKER (daemon-injected). Strip the RAY_ prefix.
RAY_ROLE=${NODE_ROLE#RAY_}
if [[ "$RAY_ROLE" != "HEAD" && "$RAY_ROLE" != "WORKER" ]]; then
    log "error: unknown cluster role NODE_ROLE='${NODE_ROLE:-<unset>}'" >&2
    exit 1
fi

# NODE_ADDR carries a CIDR suffix; strip it. On the head, PRIMARY_ADDR is self.
RAY_NODE_IP=${NODE_ADDR:-${PRIMARY_ADDR:-}}
RAY_NODE_IP=${RAY_NODE_IP%%/*}
if [[ -z "$RAY_NODE_IP" ]]; then
    log "error: could not determine this node's overlay IP (NODE_ADDR/PRIMARY_ADDR unset)" >&2
    exit 1
fi
export RAY_NODE_IP_ADDRESS=$RAY_NODE_IP
log "pod=$(hostname) role=$RAY_ROLE node_ip=$RAY_NODE_IP cluster_nodes=${NUM_NODES:-?}"

# --- Fabric preflight ------------------------------------------------------- #
# Self-heal NCCL_SOCKET_IFNAME against the interface that actually owns this
# pod's overlay IP, and fill the NCCL/Gloo gaps the daemon leaves. The record is
# sourceable by workloads that want the healed values (login shells see the
# daemon's original guess — see runpod/host CLUSTER_PAYLOADS.md).
FABRIC_LIB=${RAY_FABRIC_LIB:-/opt/ray-cluster/fabric.sh}
FABRIC_DIR=${RAY_FABRIC_DIR:-/tmp}
if [[ -f "$FABRIC_LIB" ]]; then
    # shellcheck source=/dev/null
    . "$FABRIC_LIB"
    export FABRIC_NODE_IP=$RAY_NODE_IP
    fabric_self_heal_ifname
    fabric_defaults
    fabric_write_env_record "$FABRIC_DIR/cluster-fabric.env"
    log "fabric preflight complete: NCCL_SOCKET_IFNAME=${NCCL_SOCKET_IFNAME:-<unset>} NCCL_IB_DISABLE=${NCCL_IB_DISABLE:-<unset>}"
else
    log "note: fabric library not found at $FABRIC_LIB; skipping preflight"
fi

# --- Metrics-port collision fallback ---------------------------------------- #
# Pin the Ray metrics port to RAY_METRICS_PORT so the host scraper's target is
# stable. If something already holds it, start WITHOUT the flag (Ray picks a
# free port) and log loudly rather than crash-looping — the metrics scrape
# degrades, the cluster still forms.
metrics_flag() {
    local port=$1
    if command -v ss > /dev/null 2>&1 && ss -ltnH "sport = :$port" 2> /dev/null | grep -q .; then
        log "warn: metrics port $port already in use; starting Ray without --metrics-export-port (host scrape will be unavailable)" >&2
        return 0
    fi
    printf -- '--metrics-export-port=%s' "$port"
}

# --- Common ray start flags ------------------------------------------------- #
# --disable-usage-stats: no phone-home from customer clusters.
# --dashboard-agent-listen-port: pin the per-node agent so the local liveness
#   probe and HEALTHCHECK have a fixed endpoint.
common_args=(
    --node-ip-address="$RAY_NODE_IP_ADDRESS"
    --dashboard-agent-listen-port="$RAY_DASHBOARD_AGENT_PORT"
    --disable-usage-stats
    --block
)
mapfile -t metrics_args < <(metrics_flag "$RAY_METRICS_PORT")

if [[ "$RAY_ROLE" == "HEAD" ]]; then
    log "starting Ray HEAD (gcs :$RAY_GCS_PORT, dashboard 0.0.0.0:$RAY_DASHBOARD_PORT, metrics :$RAY_METRICS_PORT)"
    exec ray start --head \
        --port="$RAY_GCS_PORT" \
        --dashboard-host=0.0.0.0 \
        --dashboard-port="$RAY_DASHBOARD_PORT" \
        "${metrics_args[@]}" \
        "${common_args[@]}"
fi

# --- Worker: wait for the head GCS, then register --------------------------- #
if [[ -z "${PRIMARY_ADDR:-}" ]]; then
    log "error: worker has no PRIMARY_ADDR to register against" >&2
    exit 1
fi
HEAD_IP=${PRIMARY_ADDR%%/*}
RAY_HEAD_WAIT_SECONDS=${RAY_HEAD_WAIT_SECONDS:-600}
log "waiting up to ${RAY_HEAD_WAIT_SECONDS}s for Ray head GCS at $HEAD_IP:$RAY_GCS_PORT..."
deadline=$(( $(date +%s) + RAY_HEAD_WAIT_SECONDS ))
until (echo > "/dev/tcp/$HEAD_IP/$RAY_GCS_PORT") 2> /dev/null; do
    if [[ "$(date +%s)" -ge "$deadline" ]]; then
        log "error: Ray head not reachable at $HEAD_IP:$RAY_GCS_PORT after ${RAY_HEAD_WAIT_SECONDS}s; supervisord will retry" >&2
        exit 1
    fi
    sleep 5
done
log "Ray head reachable; registering worker with $HEAD_IP:$RAY_GCS_PORT"
exec ray start \
    --address="$HEAD_IP:$RAY_GCS_PORT" \
    "${metrics_args[@]}" \
    "${common_args[@]}"
