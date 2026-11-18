#!/bin/bash
# ---------------------------------------------------------------------------- #
# ray-cluster inference variant post-start hook
#
# Invoked by the shared /start.sh (`execute_script "/post_start.sh"`). Runs the
# Ray image's own hook (/post_start.ray.sh, renamed at build time: monitoring
# bringup and the Ray scrape job), then, on the head, adds Prometheus jobs
# for the inference stack:
#   - vllm: 127.0.0.1:8000, vLLM's engine metrics, with no key (vLLM is
#     reachable only from this pod);
#   - litellm: 127.0.0.1:4000/metrics, the API's request metrics, sending the
#     master key from /etc/litellm/master_key (root-only, written by
#     /opt/runpod/inference/start), as LiteLLM requires it on /metrics.
# Until they are up, the targets are simply down.
#
# Never hard-fails the pod: no `set -e`, always exits 0.
# ---------------------------------------------------------------------------- #
set +e

log() { echo "[ray-inference] $*"; }

PROM_CONFIG=/etc/prometheus/prometheus.yml

/post_start.ray.sh

# The head is rank 0, as for Ray's hook; vLLM serves only there, and only with
# a MODEL_REPO (without one, the targets would only ever be down).
if [[ "${NODE_RANK:-}" != "0" || "${RAY_CLUSTER_METRICS:-1}" == "0" || -z "${MODEL_REPO:-}" ]]; then
    exit 0
fi

if [[ ! -f "$PROM_CONFIG" ]]; then
    log "note: $PROM_CONFIG absent; skipping inference scrape wiring"
elif grep -q "job_name: vllm" "$PROM_CONFIG"; then
    log "inference scrape jobs already present"
else
    log "adding vLLM (127.0.0.1:8000) and LiteLLM (127.0.0.1:4000) scrape jobs"
    {
        echo "  - job_name: vllm"
        echo "    static_configs:"
        echo "      - targets: ['127.0.0.1:8000']"
        echo "  - job_name: litellm"
        echo "    metrics_path: /metrics/"
        echo "    authorization:"
        echo "      credentials_file: /etc/litellm/master_key"
        echo "    static_configs:"
        echo "      - targets: ['127.0.0.1:4000']"
    } >> "$PROM_CONFIG"
    # Prometheus runs without --web.enable-lifecycle, so restart to reload.
    supervisorctl restart prometheus > /dev/null 2>&1
fi
exit 0
