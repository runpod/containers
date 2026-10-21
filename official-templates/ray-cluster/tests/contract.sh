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
#      addresses (what pkg/rayready polls and parses), both nodes serve Ray
#      metrics on 20217, and both pass the
#      local HEALTHCHECK. The dashboard and metrics checks run from the
#      worker, over the docker bridge, as the host does.
#
# Usage: contract.sh <image-ref> [<image-ref>...]
# Set RAY_CONTRACT_FIXTURE_DIR to save the head's /nodes and /metrics payloads
# (host-test fixtures for pkg/rayready and pkg/raymetrics).
set -euo pipefail

readonly CONTRACT=v1
readonly DASHBOARD_PORT=8265
readonly METRICS_PORT=20217
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

# expect_boot_error <image> <message> <docker run args...>
expect_boot_error() {
    local image=$1 want=$2 out
    shift 2
    if out=$(docker run --rm -e NODE_RANK=0 --add-host node-0:127.0.0.1 "$@" "$image" true 2>&1); then
        fail "boot with [$*] succeeded; want it refused"
    fi
    grep -qF "$want" <<< "$out" || fail "boot with [$*] did not report '$want'; got: $out"
    pass "refused [$*]"
}

# in_worker <cmd...>: run in the worker container (reaches the head over the bridge).
in_worker() { docker exec "$run_id-worker" "$@"; }

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

# The head dashboard's health endpoint, as pkg/rayready polls it. Ray 2.53
# serves the unified /api/healthz on the agent port only; on the dashboard
# port it is a 404.
head_healthy() {
    in_worker curl -fsS "http://$HEAD_IP:$DASHBOARD_PORT/api/gcs_healthz" | grep -q success
}

worker_waiting_for_head() {
    docker logs "$run_id-worker" 2>&1 | grep -qF "waiting for the Ray head GCS at node-0"
}

# Body captured first: grep -q exiting early would SIGPIPE curl under pipefail.
serves_ray_metrics() { # <ip>
    local body
    body=$(in_worker curl -fsS "http://$1:$METRICS_PORT/metrics") && grep -q '^ray_' <<< "$body"
}

# Both nodes ALIVE at the addresses they were started with, the match
# pkg/rayready makes against each member's PeerIp.
both_alive() {
    local alive
    alive=$(in_worker curl -fsS "http://$HEAD_IP:$DASHBOARD_PORT$NODES_PATH" |
        python3 -c 'import json,sys; print(" ".join(sorted(n["node_ip"] for n in json.load(sys.stdin)["data"]["result"]["result"] if n["state"] == "ALIVE")))') &&
        [[ "$alive" == "$HEAD_IP $WORKER_IP" ]]
}

check_image() {
    local image=$1
    echo "=== $image"

    # 1. Label and entrypoint.
    [[ "$(docker image inspect -f '{{index .Config.Labels "com.runpod.ray-cluster.contract"}}' "$image")" == "$CONTRACT" ]] ||
        fail "label com.runpod.ray-cluster.contract != $CONTRACT"
    [[ "$(docker image inspect -f '{{json .Config.Entrypoint}}' "$image")" == '["/opt/runpod/ray/entrypoint"]' ]] ||
        fail "ENTRYPOINT is not /opt/runpod/ray/entrypoint"
    pass "contract label $CONTRACT and ENTRYPOINT"

    # 2. Port overrides are refused before Ray starts.
    expect_boot_error "$image" "RAY_METRICS_PORT is fixed at $METRICS_PORT" -e RAY_METRICS_PORT=8080
    expect_boot_error "$image" "RAY_DASHBOARD_PORT is fixed at $DASHBOARD_PORT" -e RAY_DASHBOARD_PORT=8266
    expect_boot_error "$image" "must not set --metrics-export-port" -e RAY_START_EXTRA_ARGS="--num-cpus=1 --metrics-export-port=9999"
    expect_boot_error "$image" "must not set --dashboard-port" -e RAY_START_EXTRA_ARGS="--dashboard-port 9000"

    # 3. Not a cluster pod: CMD runs, Ray does not.
    [[ "$(docker run --rm "$image" bash -c '[[ -e /tmp/ray ]] && echo ray || echo plain' | tail -n 1)" == plain ]] ||
        fail "a pod without NODE_RANK started Ray"
    pass "no NODE_RANK boots CMD without Ray"

    # 4. Two-node formation. CMD is overridden so only Ray runs. Each pod gets
    # its node-<rank> hostname, as on Runpod (the inherited monitoring stack
    # keys the head off it).
    docker network create --subnet "$SUBNET" "$run_id" > /dev/null
    local topo=(-e NUM_NODES=2 --shm-size=1g --network "$run_id")

    # The worker starts while the head isn't running: node-0 is not in its
    # /etc/hosts yet. It must wait, not exit or start Ray.
    docker run -d --name "$run_id-worker" --hostname node-1 --ip "$WORKER_IP" "${topo[@]}" \
        --add-host "node-1:$WORKER_IP" -e NODE_RANK=1 "$image" sleep infinity > /dev/null
    wait_for "worker waiting for node-0" 120 worker_waiting_for_head
    sleep 10
    [[ "$(docker inspect -f '{{.State.Running}}' "$run_id-worker")" == true ]] ||
        fail "the worker exited while node-0 was missing"
    ! in_worker test -e /tmp/ray/session_latest || fail "the worker started Ray with no head to join"
    pass "worker waits while node-0 is missing from /etc/hosts"

    docker run -d --name "$run_id-head" --hostname node-0 --ip "$HEAD_IP" "${topo[@]}" \
        --add-host "node-0:$HEAD_IP" --add-host "node-1:$WORKER_IP" -e NODE_RANK=0 "$image" sleep infinity > /dev/null
    wait_for "head /api/gcs_healthz success" 180 head_healthy
    pass "head /api/gcs_healthz reports success over the bridge"

    # The host's sync adds the now-running head to the worker's membership.
    in_worker sh -c "echo '$HEAD_IP node-0' >> /etc/hosts"

    wait_for "both nodes ALIVE" 180 both_alive
    pass "State API lists both nodes ALIVE at $HEAD_IP and $WORKER_IP"

    local ip
    for ip in "$HEAD_IP" "$WORKER_IP"; do
        wait_for "ray_* metrics on $ip:$METRICS_PORT" 60 serves_ray_metrics "$ip"
    done
    pass "both nodes serve Ray metrics on $METRICS_PORT"

    local node
    for node in head worker; do
        docker exec "$run_id-$node" /opt/runpod/ray/health || fail "HEALTHCHECK fails on the $node"
    done
    pass "HEALTHCHECK passes on both nodes"

    if [[ -n "${RAY_CONTRACT_FIXTURE_DIR:-}" ]]; then
        local dir
        dir="$RAY_CONTRACT_FIXTURE_DIR/$(tr '/:' '__' <<< "$image")"
        mkdir -p "$dir"
        in_worker curl -fsS "http://$HEAD_IP:$DASHBOARD_PORT$NODES_PATH" > "$dir/nodes.json"
        in_worker curl -fsS "http://$HEAD_IP:$METRICS_PORT/metrics" > "$dir/metrics.txt"
        pass "fixtures saved to $dir"
    fi

    cleanup
}

for image in "$@"; do
    check_image "$image"
done
echo "contract $CONTRACT: all checks passed"
