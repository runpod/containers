#!/usr/bin/env bash
# Local Ray health probe behind the Docker HEALTHCHECK, modelled on KubeRay's
# probes (`wget ... | grep success`). The authoritative cluster readiness and
# liveness signal is the host-side poller (runpod/host pkg/rayready); this is
# the in-container mirror, handy by hand: /opt/runpod/ray/health
#
# Exits 0 when this node's dashboard agent reports healthy. Ray >= 2.53 serves
# the unified /api/healthz on the agent port, covering the raylet and its GCS
# connection; the dashboard port (8265) only serves /api/gcs_healthz.
set -uo pipefail

readonly DASHBOARD_AGENT_PORT=52365

# A plain (non-cluster) pod runs no Ray, so there is nothing to be unhealthy.
[[ -n "${NODE_ROLE:-}" ]] || exit 0

wget --tries 1 -T "${RAY_HEALTH_TIMEOUT:-5}" -q -O- "http://127.0.0.1:$DASHBOARD_AGENT_PORT/api/healthz" 2> /dev/null |
    grep -q success
