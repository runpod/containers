#!/bin/bash
# ---------------------------------------------------------------------------- #
# ray-cluster post-start hook
#
# Invoked by the shared /start.sh (`execute_script "/post_start.sh"`). It layers
# Ray onto the inherited pytorch-cluster monitoring:
#
#   1. Run the inherited /post_start.cluster.sh (renamed from the parent image's
#      /post_start.sh at build time). That brings up node_exporter + dcgm-exporter
#      on every node and Prometheus + Grafana on the head, and — because
#      /etc/supervisor/conf.d/ray.conf ships in this image — supervisord also
#      autostarts the `ray-node` program, i.e. Ray itself.
#   2. On the head, add a Prometheus scrape job for each node's Ray metrics
#      endpoint so Ray metrics land in the same Prometheus/Grafana as the GPU and
#      system metrics.
#
# Never hard-fail the pod: no `set -e`, always exit 0. Ray's own lifecycle is
# supervisord's job; this hook only wires up scraping.
# ---------------------------------------------------------------------------- #
set +e

log() { echo "[ray-cluster] $*"; }

PROM_CONFIG=/etc/prometheus/prometheus.yml
RAY_METRICS_PORT=${RAY_METRICS_PORT:-8080}

# Head detection: prefer the daemon-injected role, fall back to the node-0
# hostname convention the monitoring layer uses (PRIMARY_ADDR is node-0, which is
# also the Ray head — same node).
is_ray_head() {
    if [[ -n "${NODE_ROLE:-}" ]]; then
        [[ "$NODE_ROLE" == "RAY_HEAD" ]]
    else
        [[ "$(hostname -s)" == "node-0" ]]
    fi
}

# 1. Inherited monitoring bringup (exporters everywhere, Prometheus/Grafana on
#    head) + supervisord, which autostarts ray-node.
if [[ -x /post_start.cluster.sh ]]; then
    log "running inherited cluster monitoring bringup"
    /post_start.cluster.sh
else
    log "warn: /post_start.cluster.sh not found; monitoring stack not started"
fi

# 2. Head-only: add Ray scrape targets and reload Prometheus. Ray exports
#    per-node Prometheus metrics on RAY_METRICS_PORT; scrape every node-* peer
#    from /etc/hosts (same source the inherited config uses), falling back to the
#    head itself when no peers are listed.
add_ray_scrape_targets() {
    if [[ ! -f "$PROM_CONFIG" ]]; then
        log "note: $PROM_CONFIG absent; skipping Ray scrape wiring"
        return
    fi
    if grep -q "job_name: ray" "$PROM_CONFIG"; then
        log "Ray scrape job already present; leaving it"
        return
    fi
    local nodes
    nodes=$(awk '{for (i = 2; i <= NF; i++) if ($i ~ /^node-/) print $i}' /etc/hosts | sort -u)
    [[ -z "$nodes" ]] && nodes=$(hostname -s)
    log "Ray scrape targets: $(echo "$nodes" | tr '\n' ' ') on :$RAY_METRICS_PORT"
    {
        echo "  - job_name: ray"
        echo "    static_configs:"
        echo "      - targets:"
        for n in $nodes; do echo "          - '${n}:${RAY_METRICS_PORT}'"; done
    } >> "$PROM_CONFIG"
    # The inherited config binds Prometheus without --web.enable-lifecycle, so a
    # supervisorctl restart is the reload path.
    if supervisorctl status prometheus > /dev/null 2>&1; then
        log "restarting Prometheus to pick up Ray targets"
        supervisorctl restart prometheus > /dev/null 2>&1
    fi
}

if is_ray_head; then
    add_ray_scrape_targets
else
    log "not the head node; Ray scrape wiring is head-only"
fi

log "post-start complete"
exit 0
