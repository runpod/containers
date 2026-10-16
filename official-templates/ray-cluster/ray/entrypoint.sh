#!/usr/bin/env bash
# Ray cluster image entrypoint (contract v1). The only Ray launch logic on a
# Runpod Ray cluster: the host daemon injects topology env and observes from
# outside the container, and this script turns that env into a running Ray
# node before handing off to the container's CMD.
#
# It does exactly this, in order:
#   1. enforce the contract ports (dashboard 8265, metrics 20217);
#   2. take the role from NODE_RANK (rank 0 is the head) and this node's
#      address from its node-<NODE_RANK> entry in /etc/hosts;
#   3. on a worker, wait with no deadline for the head GCS at node-0;
#   4. `ray start` with the contract ports, plus $RAY_START_EXTRA_ARGS;
#   5. exec "$@" (the customer CMD, /start.sh by default).
#
# The topology it reads is only what the host alone knows: NODE_RANK, NUM_NODES
# and the cluster membership in /etc/hosts (node-0 ... node-N). The other
# cluster env the host sets (PRIMARY_ADDR, NODE_ADDR, NODE_ROLE, ...) is fixed
# at create and goes stale, or is left unset, when the head isn't running then.
# /etc/hosts doesn't: the host appends missing members on every sync, so a
# worker that started before the head joins once node-0 appears.
#
# It does not install packages, write readiness markers, or probe the fabric:
# the host pins the fabric NIC and polls readiness itself. The ports are a
# contract with runpod/host (pkg/rayready, pkg/raymetrics), which reads nothing
# from the pod, so an override would make the node invisible to the host. That
# is why an override fails the boot instead of being honoured.
set -uo pipefail

readonly CONTRACT_DASHBOARD_PORT=8265
readonly CONTRACT_METRICS_PORT=20217
readonly DASHBOARD_AGENT_PORT=52365

log() { echo "[ray-entrypoint] $*"; }
die() {
    echo "[ray-entrypoint] error: $*" >&2
    exit 1
}

[[ $# -gt 0 ]] || set -- /start.sh

# Not a cluster pod (no daemon-injected rank): run the CMD without Ray, so the
# image still boots as a plain pod.
if [[ -z "${NODE_RANK:-}" ]]; then
    log "NODE_RANK unset: not a Ray cluster pod, starting without Ray"
    exec "$@"
fi
[[ "$NODE_RANK" =~ ^[0-9]+$ ]] || die "NODE_RANK '$NODE_RANK' is not a node rank"

# --- 1. Contract ports ------------------------------------------------------ #
require_port() { # <var> <contract value>
    local name=$1 want=$2 got=${!1:-$2}
    [[ "$got" == "$want" ]] ||
        die "$name is fixed at $want by the Ray cluster image contract (got '$got'). Remove the override and move your own service to a different port."
}
require_port RAY_DASHBOARD_PORT "$CONTRACT_DASHBOARD_PORT"
require_port RAY_METRICS_PORT "$CONTRACT_METRICS_PORT"

read -ra extra_args <<< "${RAY_START_EXTRA_ARGS:-}"
for arg in "${extra_args[@]}"; do
    case "$arg" in
        --metrics-export-port | --metrics-export-port=*)
            die "RAY_START_EXTRA_ARGS must not set --metrics-export-port: RAY_METRICS_PORT is fixed at $CONTRACT_METRICS_PORT" ;;
        --dashboard-port | --dashboard-port=*)
            die "RAY_START_EXTRA_ARGS must not set --dashboard-port: RAY_DASHBOARD_PORT is fixed at $CONTRACT_DASHBOARD_PORT" ;;
    esac
done

# --- 2. Role and node address ----------------------------------------------- #
# hosts_ip <name>: the IPv4 address /etc/hosts maps <name> to, read from the
# file itself on every call (not the resolver), since the host rewrites it
# while the pod runs.
hosts_ip() {
    awk -v name="$1" '
        $1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {
            for (i = 2; i <= NF && $i !~ /^#/; i++) if ($i == name) { print $1; exit }
        }' /etc/hosts
}

# The control plane gives rank 0 the head role, so the rank decides it.
if [[ "$NODE_RANK" == 0 ]]; then role="head"; else role="worker"; fi
self="node-$NODE_RANK"

# This pod is running, so the host listed it at create. The short wait only
# covers a write still in flight; a pod missing from its own membership is a
# host bug, and failing loudly beats binding Ray to a guessed address.
node_ip=""
for _ in $(seq 1 30); do
    node_ip=$(hosts_ip "$self")
    [[ -n "$node_ip" ]] && break
    sleep 2
done
[[ -n "$node_ip" ]] || die "$self is not in /etc/hosts; the host lists every cluster member there"
gcs_port=${RAY_GCS_PORT:-6379}
log "role=$role node=$self node_ip=$node_ip num_nodes=${NUM_NODES:-?}"

# A derived image that upgraded Ray drifts from the host's pinned parsers.
if [[ -n "${RAY_CLUSTER_RAY_VERSION:-}" ]]; then
    installed=$(ray --version 2> /dev/null | awk '{print $NF}')
    [[ "$installed" == "$RAY_CLUSTER_RAY_VERSION" ]] ||
        log "warn: Ray $installed is installed but this image supports $RAY_CLUSTER_RAY_VERSION; cluster readiness and metrics may misreport"
fi

common_args=(
    --node-ip-address="$node_ip"
    --metrics-export-port="$CONTRACT_METRICS_PORT"
    --dashboard-agent-listen-port="$DASHBOARD_AGENT_PORT"
)

# Waits for a local endpoint after `ray start` returns: a port Ray could not
# bind kills its agent asynchronously, after `ray start` has already succeeded.
wait_listening() { # <port> <what>
    local port=$1 what=$2
    for _ in $(seq 1 60); do
        (echo > "/dev/tcp/127.0.0.1/$port") 2> /dev/null && return 0
        sleep 1
    done
    die "$what did not come up on port $port within 60s; see /tmp/ray/session_latest/logs"
}

if [[ "$role" == head ]]; then
    # Point the dashboard's Metrics tab at the head's Prometheus + Grafana
    # (started by /post_start.sh). The iframe host is what the browser loads.
    if [[ "${RAY_CLUSTER_METRICS:-1}" != "0" ]]; then
        export RAY_PROMETHEUS_HOST=${RAY_PROMETHEUS_HOST:-http://127.0.0.1:9090}
        export RAY_GRAFANA_HOST=${RAY_GRAFANA_HOST:-http://127.0.0.1:3300}
        if [[ -n "${RUNPOD_POD_ID:-}" ]]; then
            export RAY_GRAFANA_IFRAME_HOST=${RAY_GRAFANA_IFRAME_HOST:-https://${RUNPOD_POD_ID}-8889.${RUNPOD_PROXY_BASE:-proxy.runpod.net}}
        fi
    fi

    # --- 4. Start the head ---------------------------------------------- #
    log "starting Ray head: gcs :$gcs_port, dashboard 0.0.0.0:$CONTRACT_DASHBOARD_PORT, metrics :$CONTRACT_METRICS_PORT"
    ray start --head \
        --port="$gcs_port" \
        --dashboard-host=0.0.0.0 \
        --dashboard-port="$CONTRACT_DASHBOARD_PORT" \
        "${common_args[@]}" "${extra_args[@]}" ||
        die "ray start --head failed; see /tmp/ray/session_latest/logs"
    wait_listening "$CONTRACT_DASHBOARD_PORT" "Ray dashboard"
    wait_listening "$CONTRACT_METRICS_PORT" "Ray metrics endpoint"
    log "Ray head started"
    exec "$@"
fi

# --- 3. Worker: wait for the head GCS ----------------------------------- #
# No deadline: a missing head is a reason to wait, not to exit. node-0 is
# re-resolved on every attempt, because it is absent from /etc/hosts while the
# head is stopped, and the host adds it back (with its overlay peer) once the
# head runs again. Until then the host reports this rank as not alive.
log "waiting for the Ray head GCS at node-0:$gcs_port"
started=$SECONDS
next_log=$((SECONDS + 60))
while :; do
    head_ip=$(hosts_ip node-0)
    # Bounded per attempt: a connect to a silent overlay peer can hang for minutes.
    if [[ -n "$head_ip" ]] && timeout 5 bash -c "echo > /dev/tcp/$head_ip/$gcs_port" 2> /dev/null; then
        break
    fi
    if ((SECONDS >= next_log)); then
        if [[ -n "$head_ip" ]]; then
            log "still waiting for the Ray head GCS at node-0 ($head_ip:$gcs_port), $((SECONDS - started))s"
        else
            log "still waiting for node-0 to appear in /etc/hosts (head not running), $((SECONDS - started))s"
        fi
        next_log=$((SECONDS + 60))
    fi
    sleep 5
done

# --- 4. Start the worker ---------------------------------------------------- #
log "joining Ray head at node-0 ($head_ip:$gcs_port)"
ray start --address="$head_ip:$gcs_port" "${common_args[@]}" "${extra_args[@]}" ||
    die "ray start failed to join $head_ip:$gcs_port; see /tmp/ray/session_latest/logs"
wait_listening "$CONTRACT_METRICS_PORT" "Ray metrics endpoint"
log "Ray worker joined"
exec "$@"
