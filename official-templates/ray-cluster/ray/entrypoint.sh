#!/usr/bin/env bash
# Ray cluster image entrypoint. The host daemon sets the topology env and
# observes Ray from outside the container; this script turns that env into a
# running Ray node before handing off to the container's CMD.
#
# It does exactly this, in order:
#   1. validate the ports (RAY_DASHBOARD_PORT, RAY_METRICS_PORT, RAY_GCS_PORT),
#      and turn on Ray's token authentication with the cluster's shared secret;
#   2. take the role from NODE_RANK (rank 0 is the head) and this node's
#      address from its node-<NODE_RANK> entry in /etc/hosts;
#   3. on a worker, wait with no deadline for the head GCS at node-0;
#   4. `ray start` on those ports, plus $RAY_START_EXTRA_ARGS;
#   5. on a worker, do 3 and 4 in the background and keep rejoining there:
#      its raylet exits with the head, and a restarted head is a new cluster
#      nothing else rejoins;
#   6. exec "$@" (the customer CMD, /start.sh by default); on a worker, at
#      once, with the Jupyter env cleared so /start.sh leaves Jupyter to the
#      head.
#
# The topology it reads is only what the host alone knows: NODE_RANK, NUM_NODES
# and the cluster membership in /etc/hosts (node-0 ... node-N). The other
# cluster env the host sets (PRIMARY_ADDR, NODE_ADDR, NODE_ROLE, ...) is fixed
# at create and goes stale, or is left unset, when the head isn't running then.
# /etc/hosts doesn't: the host rewrites it to the running members on every
# sync, so node-0 is absent while the head is stopped and returns at the
# head's current address once it runs again.
#
# runpod/host (pkg/rayready, pkg/raymetrics) reads the dashboard and metrics ports from this
# container's RAY_DASHBOARD_PORT and RAY_METRICS_PORT, which the image sets in
# its ENV, so they are honoured as set, and Ray must not be started on any
# other port.
set -uo pipefail

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
# Bounded so the arithmetic below can't overflow; canonical (no leading zeros)
# and re-exported, so a rank of "00" is the head here and in /post_start.sh.
[[ "$NODE_RANK" =~ ^[0-9]{1,5}$ ]] || die "NODE_RANK '$NODE_RANK' is not a node rank"
export NODE_RANK=$((10#$NODE_RANK))

# --- 1. Ports --------------------------------------------------------------- #
# require_port <var>: <var> must hold a TCP port (1-65535); it is re-exported
# without leading zeros, so the host, this script and the CMD agree on it. The
# values reach a `bash -c` string in wait_for_head and the nginx config, so
# only a plain port number gets that far. Unset or empty is refused like any
# other invalid value: the host reads the same variable and would not find Ray.
require_port() { # <var>
    local name=$1 value=${!1:-}
    if ! [[ "$value" =~ ^[0-9]{1,5}$ ]] || ((10#$value < 1 || 10#$value > 65535)); then
        die "$name '$value' is not a TCP port (1-65535)"
    fi
    export "$name=$((10#$value))"
}
require_port RAY_DASHBOARD_PORT
require_port RAY_METRICS_PORT
export RAY_GCS_PORT=${RAY_GCS_PORT:-6379}
require_port RAY_GCS_PORT
gcs_port=$RAY_GCS_PORT

# The ports go to Ray only from their variables, which the host reads.
read -ra extra_args <<< "${RAY_START_EXTRA_ARGS:-}"
for arg in "${extra_args[@]}"; do
    case "$arg" in
        --metrics-export-port | --metrics-export-port=*)
            die "RAY_START_EXTRA_ARGS must not set --metrics-export-port: set RAY_METRICS_PORT instead" ;;
        --dashboard-port | --dashboard-port=*)
            die "RAY_START_EXTRA_ARGS must not set --dashboard-port: set RAY_DASHBOARD_PORT instead" ;;
        *) ;;
    esac
done

# The front door on 8266 proxies to the dashboard (ray-dashboard.conf).
# shellcheck disable=SC2016 # $ray_dashboard is nginx's
printf 'set $ray_dashboard 127.0.0.1:%s;\n' "$RAY_DASHBOARD_PORT" > /etc/nginx/ray-dashboard-address.conf

# --- 1b. Token authentication ---------------------------------------------- #
# Unauthenticated, the dashboard's API is job submission, i.e. remote code
# execution (ShadowRay, CVE-2023-48022). Ray's own token auth (RAY_AUTH_MODE=
# token) gates the dashboard HTTP API, each node's dashboard agent (52365,
# which serves job submission and logs; Ray >= 2.54) and the GCS/raylet gRPC, so
# every node, driver and `ray` CLI call must carry the same token. Ray reads it
# from RAY_AUTH_TOKEN (or RAY_AUTH_TOKEN_PATH); a customer-set value wins,
# else it is the cluster's shared secret: RAY_DASHBOARD_PASSWORD, else
# JUPYTER_PASSWORD. Exported here, so the CMD, Jupyter kernels and SSH
# sessions (/start.sh copies the env to /etc/rp_environment) inherit it.
#
# Fail closed: with no secret the boot fails rather than run an open
# dashboard. RAY_AUTH_MODE=disabled is the explicit opt-out, for customers who
# never expose the dashboard. Any other value (a typo, "off") is refused: this
# script would log auth as on while Ray, which recognises only "token", might
# run open.
export RAY_AUTH_MODE=${RAY_AUTH_MODE:-token}
RAY_AUTH_MODE=${RAY_AUTH_MODE,,}
[[ "$RAY_AUTH_MODE" == token || "$RAY_AUTH_MODE" == disabled ]] ||
    die "RAY_AUTH_MODE '$RAY_AUTH_MODE' is not 'token' or 'disabled'"
if [[ "$RAY_AUTH_MODE" == disabled ]]; then
    log "warn: RAY_AUTH_MODE=disabled: the Ray dashboard and GCS accept unauthenticated requests, including job submission. Never map $RAY_DASHBOARD_PORT publicly."
else
    if [[ -z "${RAY_AUTH_TOKEN:-}" && -z "${RAY_AUTH_TOKEN_PATH:-}" ]]; then
        if [[ -n "${RAY_DASHBOARD_PASSWORD:-}" ]]; then
            export RAY_AUTH_TOKEN=$RAY_DASHBOARD_PASSWORD
            token_source=RAY_DASHBOARD_PASSWORD
        elif [[ -n "${JUPYTER_PASSWORD:-}" ]]; then
            export RAY_AUTH_TOKEN=$JUPYTER_PASSWORD
            token_source=JUPYTER_PASSWORD
        else
            die "Ray token authentication needs a shared secret: set RAY_DASHBOARD_PASSWORD (or JUPYTER_PASSWORD) to the same value on every node. RAY_AUTH_MODE=disabled turns authentication off; the dashboard then allows unauthenticated job submission."
        fi
    elif [[ -n "${RAY_AUTH_TOKEN:-}" ]]; then
        token_source=RAY_AUTH_TOKEN
    else
        [[ -s "$RAY_AUTH_TOKEN_PATH" ]] ||
            die "RAY_AUTH_TOKEN_PATH '$RAY_AUTH_TOKEN_PATH' is not a non-empty file"
        token_source=RAY_AUTH_TOKEN_PATH
    fi
    log "Ray token authentication on (token from $token_source)"
fi

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
log "role=$role node=$self node_ip=$node_ip num_nodes=${NUM_NODES:-?} metrics_port=$RAY_METRICS_PORT"

# A derived image that upgraded Ray drifts from the host's pinned parsers.
if [[ -n "${RAY_CLUSTER_RAY_VERSION:-}" ]]; then
    installed=$(ray --version 2> /dev/null | awk '{print $NF}')
    [[ "$installed" == "$RAY_CLUSTER_RAY_VERSION" ]] ||
        log "warn: Ray $installed is installed but this image supports $RAY_CLUSTER_RAY_VERSION; cluster readiness and metrics may misreport"
fi

common_args=(
    --node-ip-address="$node_ip"
    --metrics-export-port="$RAY_METRICS_PORT"
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
        # Grafana's token proxy also accepts the cluster token, so one ?token=
        # link signs in both, while its own token (GRAFANA_PASSWORD, else
        # JUPYTER_PASSWORD, which the console's Grafana link carries) still works.
        if [[ "$RAY_AUTH_MODE" == token ]]; then
            GRAFANA_CLUSTER_TOKEN=${RAY_AUTH_TOKEN:-$(< "$RAY_AUTH_TOKEN_PATH")}
            export GRAFANA_CLUSTER_TOKEN
        fi
        if [[ -n "${RUNPOD_POD_ID:-}" && -z "${RAY_GRAFANA_IFRAME_HOST:-}" ]]; then
            proxy_base=${RUNPOD_PROXY_BASE:-proxy.runpod.net}
            export RAY_GRAFANA_IFRAME_HOST=https://${RUNPOD_POD_ID}-8889.$proxy_base
            # The panels are on Grafana's origin, so they need its cookie too:
            # the front door's ?token= login at / (the console's link) bounces
            # through the proxy's /runpod-login, which sets it and returns to
            # the dashboard. A deep link keeps its path and skips the bounce.
            export LOGIN_RETURN_URL=https://${RUNPOD_POD_ID}-8266.$proxy_base/
            # shellcheck disable=SC2016 # $uri, $after_login and $arg_token are nginx's
            printf '%s\n' 'set $after_login $uri;' 'if ($uri = /) {' \
                "    set \$after_login \"$RAY_GRAFANA_IFRAME_HOST/runpod-login?token=\$arg_token\";" '}' \
                > /etc/nginx/ray-dashboard-login.conf
        fi
    fi

    # --- 4. Start the head ---------------------------------------------- #
    log "starting Ray head: gcs :$gcs_port, dashboard 0.0.0.0:$RAY_DASHBOARD_PORT, metrics :$RAY_METRICS_PORT"
    ray start --head \
        --port="$gcs_port" \
        --dashboard-host=0.0.0.0 \
        --dashboard-port="$RAY_DASHBOARD_PORT" \
        "${common_args[@]}" "${extra_args[@]}" ||
        die "ray start --head failed; see /tmp/ray/session_latest/logs"
    wait_listening "$RAY_DASHBOARD_PORT" "Ray dashboard"
    wait_listening "$RAY_METRICS_PORT" "Ray metrics endpoint"
    log "Ray head started"
    exec "$@"
fi

# --- 3. Worker: wait for the head GCS ----------------------------------- #
# Everything from here on runs in the background (step 5), so the CMD starts
# at once: /start.sh is what brings up sshd, so a worker whose head never
# comes up is still reachable to debug.
#
# wait_for_head returns once the head GCS accepts a connection, with head_ip
# set. No deadline: a missing head is a reason to wait, not to exit. node-0 is
# re-resolved on every attempt, because it is absent from /etc/hosts while the
# head is stopped, and the host adds it back (with its overlay peer) once the
# head runs again. Until then the host reports this rank as not alive.
wait_for_head() {
    local started=$SECONDS next_log=$((SECONDS + 60))
    log "waiting for the Ray head GCS at node-0:$gcs_port"
    while :; do
        head_ip=$(hosts_ip node-0)
        # Bounded per attempt: a connect to a silent overlay peer can hang for minutes.
        if [[ -n "$head_ip" ]] && timeout 5 bash -c "echo > /dev/tcp/$head_ip/$gcs_port" 2> /dev/null; then
            return 0
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
}

# --- 4. Start the worker ---------------------------------------------------- #
join_head() {
    log "joining Ray head at node-0 ($head_ip:$gcs_port)"
    ray start --address="$head_ip:$gcs_port" "${common_args[@]}" "${extra_args[@]}"
}

# --- 5. Worker: join, then keep rejoining ----------------------------------- #
# The raylet exits when it loses the head, and a restarted head is a new GCS
# with no members, so without the rejoin the worker stays out of the cluster
# until its pod is restarted. Never exits: a failed join is retried on the
# next pass.
# A dead raylet can linger as a zombie: it is reparented to PID 1, which a CMD
# like `sleep infinity` never reaps. So match the state field, not just the name.
raylet_running() {
    local stat line
    for stat in /proc/[0-9]*/stat; do
        read -r line 2> /dev/null < "$stat" || continue
        [[ "$line" =~ ^[0-9]+\ \(raylet\)\ [^Z] ]] && return 0
    done
    return 1
}
join_forever() {
    wait_for_head
    if join_head; then
        log "Ray worker joined"
    else
        log "warn: ray start failed to join $head_ip:$gcs_port; retrying (see /tmp/ray/session_latest/logs)"
    fi
    while :; do
        sleep 10
        raylet_running && continue
        log "raylet exited; rejoining once the head is back"
        ray stop --force > /dev/null 2>&1
        wait_for_head
        join_head || log "warn: ray start failed to join $head_ip:$gcs_port; retrying"
    done
}
join_forever &

# --- 6. Hand off to the CMD ------------------------------------------------- #
# Jupyter runs on the head only: the driver belongs there, and a notebook
# server per worker is one more JUPYTER_PASSWORD login exposed for nothing
# (any node can still ray.init() into the cluster). /start.sh starts Jupyter
# only when one of these is set. Ray itself keeps the secret, as
# RAY_AUTH_TOKEN, when it came from JUPYTER_PASSWORD.
exec env -u JUPYTER_PASSWORD -u JUPYTER_DISABLE_AUTH "$@"
