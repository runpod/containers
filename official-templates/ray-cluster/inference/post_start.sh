#!/bin/bash
# ---------------------------------------------------------------------------- #
# ray-cluster inference variant post-start hook
#
# Invoked by the shared /start.sh (`execute_script "/post_start.sh"`). Runs the
# Ray image's own hook (/post_start.ray.sh, renamed at build time: monitoring
# bringup and the Ray scrape job), then, on the head, adds a Prometheus job
# for vLLM's metrics. vLLM listens on 127.0.0.1:8000 with no key (the key is
# checked by nginx on 8001), so the head's Prometheus scrapes it directly.
# Until vLLM is up, the target is simply down.
#
# Never hard-fails the pod: no `set -e`, always exits 0.
# ---------------------------------------------------------------------------- #
set +e

log() { echo "[ray-inference] $*"; }

PROM_CONFIG=/etc/prometheus/prometheus.yml

/post_start.ray.sh

# The head is rank 0, as for Ray's hook; vLLM serves only there.
if [[ "${NODE_RANK:-}" != "0" || "${RAY_CLUSTER_METRICS:-1}" == "0" ]]; then
    exit 0
fi

if [[ ! -f "$PROM_CONFIG" ]]; then
    log "note: $PROM_CONFIG absent; skipping vLLM scrape wiring"
elif grep -q "job_name: vllm" "$PROM_CONFIG"; then
    log "vLLM scrape job already present"
else
    log "adding vLLM scrape job (127.0.0.1:8000)"
    {
        echo "  - job_name: vllm"
        echo "    static_configs:"
        echo "      - targets: ['127.0.0.1:8000']"
    } >> "$PROM_CONFIG"
    # Prometheus runs without --web.enable-lifecycle, so restart to reload.
    supervisorctl restart prometheus > /dev/null 2>&1
fi
exit 0
