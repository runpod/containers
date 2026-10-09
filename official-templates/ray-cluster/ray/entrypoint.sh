#!/usr/bin/env bash
# Ray cluster image entrypoint (contract v1). The only Ray launch logic on a
# Runpod Ray cluster: the host daemon injects topology env and observes from
# outside the container, and this script turns that env into a running Ray
# node before handing off to the container's CMD.
#
# It does exactly this, in order:
#   1. enforce the contract ports (dashboard 8265, metrics 20217);
#   2. map NODE_ROLE to head/worker and strip the CIDR from NODE_ADDR;
#   3. on a worker, wait for the head GCS;
#   4. `ray start` with the contract ports, plus $RAY_START_EXTRA_ARGS;
#   5. exec "$@" (the customer CMD, /start.sh by default).
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

# Not a cluster pod (no daemon-injected role): run the CMD without Ray, so the
# image still boots as a plain pod.
if [[ -z "${NODE_ROLE:-}" ]]; then
    log "NODE_ROLE unset: not a Ray cluster pod, starting without Ray"
    exec "$@"
fi

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
case "$NODE_ROLE" in
    RAY_HEAD) role="head" ;;
    RAY_WORKER) role="worker" ;;
    *) die "unknown NODE_ROLE '$NODE_ROLE' (want RAY_HEAD or RAY_WORKER)" ;;
esac
[[ -n "${NODE_ADDR:-}" ]] || die "NODE_ADDR unset; the host injects it for every cluster pod"
node_ip=${NODE_ADDR%%/*}
gcs_port=${RAY_GCS_PORT:-6379}
log "role=$role node_ip=$node_ip node_rank=${NODE_RANK:-?} num_nodes=${NUM_NODES:-?}"

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
[[ -n "${PRIMARY_ADDR:-}" ]] || die "PRIMARY_ADDR unset; a worker needs the head's address"
head_ip=${PRIMARY_ADDR%%/*}
wait_s=${RAY_HEAD_WAIT_SECONDS:-600}
log "waiting up to ${wait_s}s for the Ray head GCS at $head_ip:$gcs_port"
deadline=$((SECONDS + wait_s))
# Bounded per attempt: a connect to a silent overlay peer can hang for minutes.
until timeout 5 bash -c "echo > /dev/tcp/$head_ip/$gcs_port" 2> /dev/null; do
    if ((SECONDS >= deadline)); then
        # Keep the pod up for debugging; the host reports this rank as not alive.
        log "error: Ray head unreachable at $head_ip:$gcs_port after ${wait_s}s; starting without Ray" >&2
        exec "$@"
    fi
    sleep 5
done

# --- 4. Start the worker ---------------------------------------------------- #
log "joining Ray head at $head_ip:$gcs_port"
ray start --address="$head_ip:$gcs_port" "${common_args[@]}" "${extra_args[@]}" ||
    die "ray start failed to join $head_ip:$gcs_port; see /tmp/ray/session_latest/logs"
wait_listening "$CONTRACT_METRICS_PORT" "Ray metrics endpoint"
log "Ray worker joined"
exec "$@"
