#!/bin/bash
# ---------------------------------------------------------------------------- #
# ray-cluster post-start hook
#
# Invoked by the shared /start.sh (`execute_script "/post_start.sh"`), after the
# image entrypoint (/opt/runpod/ray/entrypoint) has already started Ray. It
# layers Ray onto the inherited pytorch-cluster monitoring:
#
#   1. Run the inherited /post_start.cluster.sh (the parent image's
#      /post_start.sh, renamed at build time): exporters on every node,
#      Prometheus + Grafana on the head.
#   2. On the head, scrape every Ray node through the service-discovery file Ray
#      maintains, so new or rejoined nodes are picked up without config changes.
#      RAY_CLUSTER_METRICS=0 instead stops the head's Prometheus + Grafana, for
#      customers who bring their own stack.
#
# Never hard-fails the pod: no `set -e`, always exits 0.
# ---------------------------------------------------------------------------- #
set +e

log() { echo "[ray-cluster] $*"; }

PROM_CONFIG=/etc/prometheus/prometheus.yml
RAY_SD_FILE=/tmp/ray/prom_metrics_service_discovery.json

if [[ -x /post_start.cluster.sh ]]; then
    log "running inherited cluster monitoring bringup"
    /post_start.cluster.sh
else
    log "warn: /post_start.cluster.sh not found; monitoring stack not started"
fi

if [[ "${NODE_ROLE:-}" != "RAY_HEAD" ]]; then
    log "not the Ray head; nothing more to wire"
    exit 0
fi

if [[ "${RAY_CLUSTER_METRICS:-1}" == "0" ]]; then
    log "RAY_CLUSTER_METRICS=0: stopping the head Prometheus + Grafana"
    supervisorctl stop grafana-proxy grafana prometheus > /dev/null 2>&1
    exit 0
fi

if [[ ! -f "$PROM_CONFIG" ]]; then
    log "note: $PROM_CONFIG absent; skipping Ray scrape wiring"
elif grep -q "job_name: ray" "$PROM_CONFIG"; then
    log "Ray scrape job already present"
else
    log "adding Ray scrape job (targets from $RAY_SD_FILE)"
    {
        echo "  - job_name: ray"
        echo "    file_sd_configs:"
        echo "      - files: ['${RAY_SD_FILE}']"
    } >> "$PROM_CONFIG"
    # Prometheus runs without --web.enable-lifecycle, so restart to reload.
    supervisorctl restart prometheus > /dev/null 2>&1
fi

log "post-start complete"
exit 0
