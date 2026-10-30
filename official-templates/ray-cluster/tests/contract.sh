#!/usr/bin/env bash
# Image contract test for the ray-cluster image (contract v1). CPU-only, no
# Runpod credentials: runs the built image under plain Docker with fixture
# topology env, the way the host daemon would, and checks the parts runpod/host
# depends on.
#
#   1. the contract label and ENTRYPOINT are present;
#   2. a port override (env or RAY_START_EXTRA_ARGS) fails the boot with an
#      error naming the variable;
#   3. a pod with no NODE_RANK boots its CMD without Ray;
#   4. a 2-node cluster forms from only the topology the image depends on
#      (NODE_RANK, NUM_NODES and the node-N entries in /etc/hosts; none of the
#      passed-through PRIMARY_ADDR/NODE_ADDR/NODE_ROLE). The worker starts
#      first, while node-0 is missing from its /etc/hosts (head not running),
#      and must join once node-0 is added, as the host's sync does. Then: the
#      head dashboard's /api/gcs_healthz reports success and its
#      State API node list ($NODES_PATH) has both nodes ALIVE at their
#      addresses (what pkg/rayready polls and parses), and both nodes serve
#      Ray metrics on 20217. The dashboard and metrics checks run from the
#      worker, over the docker bridge, as the host does.
#   5. Ray token auth: the dashboard reports token mode; its API answers 401
#      with no token and 403 with a wrong one (the head's JUPYTER_PASSWORD,
#      which RAY_DASHBOARD_PASSWORD outranks), and 200 with the bearer token;
#      /api/authenticate sets the session cookie the UI rides. The worker
#      takes its token from JUPYTER_PASSWORD, so its join (step 4) proves both
#      fallbacks resolve to one cluster token. A boot with no secret is refused
#      (step 2), and RAY_AUTH_MODE=disabled is the explicit opt-out.
#   6. a restarted head is a new GCS: the worker, left running, must notice its
#      raylet exited and rejoin the new head by itself.
#
# Usage: contract.sh <image-ref> [<image-ref>...]
# Set RAY_CONTRACT_FIXTURE_DIR to save the head's /nodes and /metrics payloads
# (host-test fixtures for pkg/rayready and pkg/raymetrics).
set -euo pipefail

readonly CONTRACT=v1
readonly DASHBOARD_PORT=8265
readonly METRICS_PORT=20217
# The cluster token: the head gets it as RAY_DASHBOARD_PASSWORD, the worker as
# JUPYTER_PASSWORD. The head's own JUPYTER_PASSWORD is the wrong token.
readonly TOKEN=contract-test-token
readonly HEAD_JUPYTER_PASSWORD=contract-test-jupyter
readonly SUBNET=172.31.250.0/24
readonly HEAD_IP=172.31.250.10
readonly WORKER_IP=172.31.250.11
# The node query pkg/rayready makes: the State API's ALIVE nodes, read from the
# GCS. Not /nodes?view=summary, whose cache can trail the GCS.
readonly NODES_PATH='/api/v0/nodes?filter_keys=state&filter_predicates=%3D&filter_values=ALIVE&limit=10000'

fail() {
    echo "FAIL: $*" >&2
    exit 1
}
pass() { echo "ok: $*"; }

[[ $# -gt 0 ]] || fail "usage: $0 <image-ref> [<image-ref>...]"

run_id="raycontract-$$"
cleanup() {
    docker rm -f "$run_id-head" "$run_id-worker" > /dev/null 2>&1 || true
    docker network rm "$run_id" > /dev/null 2>&1 || true
}
trap cleanup EXIT

# expect_boot_error <image> <description> <message> <docker run args...>: the
# boot is refused, reporting <message>.
expect_boot_error() {
    local image=$1 what=$2 want=$3 out
    shift 3
    if out=$(docker run --rm -e NODE_RANK=0 --add-host node-0:127.0.0.1 "$@" "$image" true 2>&1); then
        fail "$what: boot with [$*] succeeded; want it refused"
    fi
    grep -qF "$want" <<< "$out" || fail "$what: boot with [$*] did not report '$want'; got: $out"
    pass "refused: $what"
}

# expect_boot_log <image> <description> <log line> <docker run args...>: the
# boot is accepted and logs <log line>. It runs as rank 1 with no node-0 in
# /etc/hosts, so it stops at the head wait with its input parsed and no Ray
# started, and the timeout ends it there.
expect_boot_log() {
    local image=$1 what=$2 want=$3 out
    shift 3
    out=$(docker run --rm -e NODE_RANK=1 --add-host node-1:127.0.0.1 "$@" \
        --entrypoint timeout "$image" 10 /opt/runpod/ray/entrypoint true 2>&1) || true
    grep -qF "$want" <<< "$out" || fail "$what: boot with [$*] did not log '$want'; got: $out"
    pass "accepted: $what"
}

# run_rows <check> <image> <row>...: each row is <description>|<want>|<env>...,
# run as <check> <image> <description> <want> -e <env>...
run_rows() {
    local check=$1 image=$2 row env fields args
    shift 2
    for row in "$@"; do
        IFS='|' read -ra fields <<< "$row"
        args=()
        for env in "${fields[@]:2}"; do args+=(-e "$env"); done
        "$check" "$image" "${fields[0]}" "${fields[1]}" "${args[@]}"
    done
}

# Runs a command in the worker container (reaches the head over the bridge).
in_worker=(docker exec "$run_id-worker")
# The worker's CMD is `sleep infinity`; PID 1 is that once the entrypoint execs.
worker_pid1_is_cmd() {
    local comm
    comm=$("${in_worker[@]}" cat /proc/1/comm) || return 1
    [[ "$comm" == sleep ]]
}

wait_for() { # <description> <timeout_s> <cmd...>
    local what=$1 timeout=$2
    shift 2
    for _ in $(seq 1 "$timeout"); do
        "$@" > /dev/null 2>&1 && return 0
        sleep 1
    done
    docker logs "$run_id-head" 2>&1 | tail -n 30 >&2 || true
    docker logs "$run_id-worker" 2>&1 | tail -n 30 >&2 || true
    fail "$what not reached within ${timeout}s"
}

# dash_code <path> [<curl args>...]: the HTTP status of a dashboard request,
# from the worker over the bridge.
dash_code() {
    local path=$1
    shift
    "${in_worker[@]}" curl -s -o /dev/null -w '%{http_code}' "$@" "http://$HEAD_IP:$DASHBOARD_PORT$path"
}

# The head dashboard's health endpoint, as pkg/rayready polls it. Public under
# token auth, like Ray's other health checks.
head_healthy() {
    "${in_worker[@]}" curl -fsS "http://$HEAD_IP:$DASHBOARD_PORT/api/gcs_healthz" | grep -q success
}

worker_waiting_for_head() {
    docker logs "$run_id-worker" 2>&1 | grep -qF "waiting for the Ray head GCS at node-0"
}

worker_rejoining() {
    docker logs "$run_id-worker" 2>&1 | grep -qF "raylet exited; rejoining"
}

# Body captured first: grep -q exiting early would SIGPIPE curl under pipefail.
serves_ray_metrics() { # <ip>
    local body
    body=$("${in_worker[@]}" curl -fsS "http://$1:$METRICS_PORT/metrics") && grep -q '^ray_' <<< "$body"
}

# Both nodes ALIVE at the addresses they were started with, the match
# pkg/rayready makes against each member's PeerIp.
both_alive() {
    local alive
    alive=$("${in_worker[@]}" curl -fsS -H "Authorization: Bearer $TOKEN" "http://$HEAD_IP:$DASHBOARD_PORT$NODES_PATH" |
        python3 -c 'import json,sys; print(" ".join(sorted(n["node_ip"] for n in json.load(sys.stdin)["data"]["result"]["result"] if n["state"] == "ALIVE")))') &&
        [[ "$alive" == "$HEAD_IP $WORKER_IP" ]]
}

check_image() {
    local image=$1
    echo "=== $image"

    # 1. Label and entrypoint.
    local label entrypoint
    label=$(docker image inspect -f '{{index .Config.Labels "com.runpod.ray-cluster.contract"}}' "$image")
    [[ "$label" == "$CONTRACT" ]] || fail "label com.runpod.ray-cluster.contract != $CONTRACT"
    entrypoint=$(docker image inspect -f '{{json .Config.Entrypoint}}' "$image")
    [[ "$entrypoint" == '["/opt/runpod/ray/entrypoint"]' ]] || fail "ENTRYPOINT is not /opt/runpod/ray/entrypoint"
    pass "contract label $CONTRACT and ENTRYPOINT"

    # The inherited monitoring bringup (pytorch-cluster after 1.4.1) picks the
    # head by NODE_RANK, like the entrypoint, not by hostname: each hostname
    # here contradicts its rank. The entrypoint is bypassed so no Ray starts.
    local head_check="source <(grep '^is_head_node()' /post_start.cluster.sh) && is_head_node"
    docker run --rm --entrypoint bash --hostname node-1 -e NODE_RANK=0 "$image" -c "$head_check" ||
        fail "inherited post-start: NODE_RANK=0 on hostname node-1 is not the head"
    ! docker run --rm --entrypoint bash --hostname node-0 -e NODE_RANK=1 "$image" -c "$head_check" ||
        fail "inherited post-start: hostname node-0 with NODE_RANK=1 is treated as the head"
    pass "inherited post-start picks the head by NODE_RANK, not hostname"

    # 2. Boot input. Refusals, one row each: <description>|<error the boot
    # must report>|<env>... All are refused before Ray starts.
    local refusals=(
        "metrics port override|RAY_METRICS_PORT is fixed at $METRICS_PORT|RAY_METRICS_PORT=8080"
        "dashboard port override|RAY_DASHBOARD_PORT is fixed at $DASHBOARD_PORT|RAY_DASHBOARD_PORT=8266"
        "metrics port in extra args|must not set --metrics-export-port|RAY_START_EXTRA_ARGS=--num-cpus=1 --metrics-export-port=9999"
        "dashboard port in extra args, split form|must not set --dashboard-port|RAY_START_EXTRA_ARGS=--dashboard-port 9000"
        "GCS port 0, below range|is not a TCP port|RAY_GCS_PORT=0"
        "GCS port 65536, above range|is not a TCP port|RAY_GCS_PORT=65536"
        "GCS port overflow|is not a TCP port|RAY_GCS_PORT=99999999999999999999"
        "GCS port not a number|is not a TCP port|RAY_GCS_PORT=abc"
        "GCS port command injection|is not a TCP port|RAY_GCS_PORT=6379; touch /tmp/pwned"
        "rank not a number|is not a node rank|NODE_RANK=abc"
        "negative rank|is not a node rank|NODE_RANK=-1"
        "rank overflow|is not a node rank|NODE_RANK=99999999999999999999"
        "rank command injection|is not a node rank|NODE_RANK=0; id"
        "no shared secret (fail closed)|Ray token authentication needs a shared secret"
        "auth mode Ray might read as off|is not 'token' or 'disabled'|RAY_AUTH_MODE=off|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "missing token file|is not a non-empty file|RAY_AUTH_TOKEN_PATH=/nonexistent"
        "empty token file|is not a non-empty file|RAY_AUTH_TOKEN_PATH=/dev/null"
    )
    run_rows expect_boot_error "$image" "${refusals[@]}"

    # Acceptances, one row each: <description>|<line the boot must log>|<env>...
    local accepts=(
        "GCS port 1, lower bound|GCS at node-0:1|RAY_GCS_PORT=1|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "GCS port 65535, upper bound|GCS at node-0:65535|RAY_GCS_PORT=65535|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "GCS port leading zeros dropped|GCS at node-0:80|RAY_GCS_PORT=00080|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "rank leading zeros dropped|role=worker node=node-1 |NODE_RANK=01|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "auth mode is case-insensitive|token authentication on (token from RAY_DASHBOARD_PASSWORD)|RAY_AUTH_MODE=TOKEN|RAY_DASHBOARD_PASSWORD=$TOKEN"
        "Disabled is the opt-out|warn: RAY_AUTH_MODE=disabled|RAY_AUTH_MODE=Disabled"
        "RAY_AUTH_TOKEN outranks the passwords|(token from RAY_AUTH_TOKEN)|RAY_AUTH_TOKEN=$TOKEN|RAY_DASHBOARD_PASSWORD=b|JUPYTER_PASSWORD=c"
        "RAY_DASHBOARD_PASSWORD outranks JUPYTER_PASSWORD|(token from RAY_DASHBOARD_PASSWORD)|RAY_DASHBOARD_PASSWORD=$TOKEN|JUPYTER_PASSWORD=c"
        "JUPYTER_PASSWORD is the last fallback|(token from JUPYTER_PASSWORD)|JUPYTER_PASSWORD=$TOKEN"
        "token file|(token from RAY_AUTH_TOKEN_PATH)|RAY_AUTH_TOKEN_PATH=/etc/hostname"
    )
    run_rows expect_boot_log "$image" "${accepts[@]}"

    # The explicit opt-out boots, with the dashboard reporting auth disabled.
    local mode
    mode=$(docker run --rm -e NODE_RANK=0 --add-host node-0:127.0.0.1 --shm-size=1g \
        -e RAY_AUTH_MODE=disabled "$image" \
        curl -fsS "http://127.0.0.1:$DASHBOARD_PORT/api/authentication_mode" 2> /dev/null | tail -n 1) ||
        fail "RAY_AUTH_MODE=disabled did not boot"
    [[ "$mode" == *'"disabled"'* ]] || fail "RAY_AUTH_MODE=disabled: dashboard reports $mode"
    pass "RAY_AUTH_MODE=disabled opts out of token auth"

    # 3. Not a cluster pod: CMD runs, Ray does not.
    local plain
    plain=$(docker run --rm "$image" bash -c '[[ -e /tmp/ray ]] && echo ray || echo plain' | tail -n 1) ||
        fail "a pod without NODE_RANK did not boot"
    [[ "$plain" == plain ]] || fail "a pod without NODE_RANK started Ray"
    pass "no NODE_RANK boots CMD without Ray"

    # 4. Two-node formation. CMD is overridden so only Ray runs. Each pod gets
    # its node-<rank> hostname, as on Runpod (the inherited monitoring stack
    # keys the head off it).
    docker network create --subnet "$SUBNET" "$run_id" > /dev/null
    local topo=(-e NUM_NODES=2 --shm-size=1g --network "$run_id")

    # The worker starts while the head isn't running: node-0 is not in its
    # /etc/hosts yet. It must wait, not exit or start Ray.
    docker run -d --name "$run_id-worker" --hostname node-1 --ip "$WORKER_IP" "${topo[@]}" \
        --add-host "node-1:$WORKER_IP" -e NODE_RANK=1 -e JUPYTER_PASSWORD="$TOKEN" \
        -e JUPYTER_DISABLE_AUTH=true "$image" sleep infinity > /dev/null
    wait_for "worker waiting for node-0" 120 worker_waiting_for_head
    sleep 10
    local running
    running=$(docker inspect -f '{{.State.Running}}' "$run_id-worker")
    [[ "$running" == true ]] || fail "the worker exited while node-0 was missing"
    ! "${in_worker[@]}" test -e /tmp/ray/session_latest || fail "the worker started Ray with no head to join"
    pass "worker waits while node-0 is missing from /etc/hosts"

    docker run -d --name "$run_id-head" --hostname node-0 --ip "$HEAD_IP" "${topo[@]}" \
        --add-host "node-0:$HEAD_IP" --add-host "node-1:$WORKER_IP" -e NODE_RANK=0 \
        -e RAY_DASHBOARD_PASSWORD="$TOKEN" -e JUPYTER_PASSWORD="$HEAD_JUPYTER_PASSWORD" \
        "$image" sleep infinity > /dev/null
    wait_for "head /api/gcs_healthz success" 180 head_healthy
    pass "head /api/gcs_healthz reports success over the bridge"

    # The host's sync adds the now-running head to the worker's membership.
    "${in_worker[@]}" sh -c "echo '$HEAD_IP node-0' >> /etc/hosts"

    wait_for "both nodes ALIVE" 180 both_alive
    pass "State API lists both nodes ALIVE at $HEAD_IP and $WORKER_IP"

    local ip
    for ip in "$HEAD_IP" "$WORKER_IP"; do
        wait_for "ray_* metrics on $ip:$METRICS_PORT" 60 serves_ray_metrics "$ip"
    done
    pass "both nodes serve Ray metrics on $METRICS_PORT"

    # Jupyter is head-only: the worker's CMD (PID 1 after the entrypoint's
    # exec) must not inherit the Jupyter env, or /start.sh would start it.
    # The metrics port comes up before the entrypoint notices and execs, so
    # wait for PID 1 to be the CMD first: until then it is the entrypoint,
    # which still has the env.
    wait_for "worker entrypoint to exec its CMD" 30 worker_pid1_is_cmd
    ! "${in_worker[@]}" grep -qzE '^(JUPYTER_PASSWORD|JUPYTER_DISABLE_AUTH)=' /proc/1/environ ||
        fail "the worker's CMD inherited the Jupyter env"
    pass "worker CMD runs without the Jupyter env"

    # 5. Token auth on the dashboard API (/api/version is not a public path).
    local code
    mode=$("${in_worker[@]}" curl -fsS "http://$HEAD_IP:$DASHBOARD_PORT/api/authentication_mode") ||
        fail "the dashboard's authentication mode is unreadable"
    [[ "$mode" == *'"token"'* ]] || fail "the dashboard does not report token authentication: $mode"
    code=$(dash_code /api/version)
    [[ "$code" == 401 ]] || fail "no token: want 401, got $code"
    code=$(dash_code /api/version -H "Authorization: Bearer $HEAD_JUPYTER_PASSWORD")
    [[ "$code" == 403 ]] || fail "wrong token (JUPYTER_PASSWORD over RAY_DASHBOARD_PASSWORD?): want 403, got $code"
    code=$(dash_code /api/version -H "Authorization: Bearer $TOKEN")
    [[ "$code" == 200 ]] || fail "bearer token: want 200, got $code"
    "${in_worker[@]}" curl -fsS -o /dev/null -D /tmp/auth-headers -X POST -H "Authorization: Bearer $TOKEN" \
        "http://$HEAD_IP:$DASHBOARD_PORT/api/authenticate" || fail "/api/authenticate rejected the token"
    "${in_worker[@]}" grep -qi 'set-cookie: ray-authentication-token=' /tmp/auth-headers ||
        fail "/api/authenticate set no session cookie"
    code=$(dash_code /api/version -H "Cookie: ray-authentication-token=$TOKEN")
    [[ "$code" == 200 ]] || fail "session cookie: want 200, got $code"
    pass "dashboard API: 401 without a token, 403 with a wrong one, 200 with the bearer token or session cookie"

    if [[ -n "${RAY_CONTRACT_FIXTURE_DIR:-}" ]]; then
        local dir
        dir="$RAY_CONTRACT_FIXTURE_DIR/$(tr '/:' '__' <<< "$image")"
        mkdir -p "$dir"
        "${in_worker[@]}" curl -fsS -H "Authorization: Bearer $TOKEN" "http://$HEAD_IP:$DASHBOARD_PORT$NODES_PATH" > "$dir/nodes.json"
        "${in_worker[@]}" curl -fsS "http://$HEAD_IP:$METRICS_PORT/metrics" > "$dir/metrics.txt"
        pass "fixtures saved to $dir"
    fi

    # 6. Rejoin. Last, so the fixtures above come from a first formation. The
    # worker isn't restarted: its own loop must bring it into the new cluster.
    docker restart "$run_id-head" > /dev/null
    wait_for "head /api/gcs_healthz success after restart" 180 head_healthy
    wait_for "worker noticing its raylet exited" 300 worker_rejoining
    wait_for "both nodes ALIVE in the restarted head" 180 both_alive
    pass "worker rejoins a restarted head without a restart of its own"

    cleanup
}

for image in "$@"; do
    check_image "$image"
done
echo "contract $CONTRACT: all checks passed"
