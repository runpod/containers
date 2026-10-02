#!/usr/bin/env bash
# ray-health.sh — local Ray health probe, modelled on KubeRay's injected
# readiness/liveness probes. Drives the Docker HEALTHCHECK and is handy to run by
# hand (`/ray-health.sh liveness`). The authoritative cluster readiness/liveness
# signal is the HOST-side poller (pkg/rayready) against this node's dashboard;
# this probe is the in-container, defence-in-depth mirror of it.
#
# Usage: ray-health.sh <liveness|readiness>
#
# KubeRay endpoints (ray-project/kuberay ray-operator/.../utils/constant.go):
#   unified (Ray >= 2.53): GET /api/healthz on the dashboard AGENT port (52365)
#   legacy head:  /api/gcs_healthz    on the dashboard port (8265)
#                 /api/local_raylet_healthz on the agent port (52365)
#   legacy worker: /api/local_raylet_healthz on the agent port (52365)
# Probe command form: wget --tries 1 -T <timeout> -q -O- <url> | grep success
set -uo pipefail

MODE=${1:-liveness}
RAY_ROLE=${NODE_ROLE#RAY_}
RAY_DASHBOARD_PORT=${RAY_DASHBOARD_PORT:-8265}
RAY_DASHBOARD_AGENT_PORT=${RAY_DASHBOARD_AGENT_PORT:-52365}
TIMEOUT=${RAY_HEALTH_TIMEOUT:-5}

# check <port> <path> — 0 iff the endpoint returns a body containing "success".
# wget ships in the runpod/pytorch base image, so this is KubeRay's probe form
# verbatim (BaseWgetHealthCommand: wget --tries 1 -T <timeout> -q -O- <url> | grep success).
check() {
    local port=$1 path=$2
    wget --tries 1 -T "$TIMEOUT" -q -O- "http://localhost:${port}/${path}" 2> /dev/null | grep -q success
}

# The unified endpoint exists on Ray >= 2.53 and is what pkg/rayready trusts;
# fall back to the legacy split endpoints on older Ray so the probe still works
# if the pinned Ray version is rolled back.
raylet_ok() {
    check "$RAY_DASHBOARD_AGENT_PORT" "api/healthz" && return 0
    check "$RAY_DASHBOARD_AGENT_PORT" "api/local_raylet_healthz"
}

gcs_ok() {
    check "$RAY_DASHBOARD_PORT" "api/healthz" && return 0
    check "$RAY_DASHBOARD_PORT" "api/gcs_healthz"
}

case "$MODE" in
    liveness)
        # Liveness = this node's raylet is up. Head additionally requires GCS.
        raylet_ok || exit 1
        [[ "$RAY_ROLE" == "HEAD" ]] && { gcs_ok || exit 1; }
        ;;
    readiness)
        # Readiness = ready to accept work: head needs GCS serving; a worker
        # needs its raylet up (whole-cluster readiness is a host-side verdict).
        if [[ "$RAY_ROLE" == "HEAD" ]]; then
            gcs_ok || exit 1
        else
            raylet_ok || exit 1
        fi
        ;;
    *)
        echo "usage: $0 <liveness|readiness>" >&2
        exit 2
        ;;
esac
