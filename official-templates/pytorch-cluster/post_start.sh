#!/bin/bash
# ---------------------------------------------------------------------------- #
# pytorch-cluster post-start hook
#
# Invoked by the shared /start.sh (`execute_script "/post_start.sh"`). Its only
# jobs are (1) render the Prometheus scrape config on the head node and (2) hand
# every long-running daemon to supervisord, which owns process lifecycle
# (autorestart, logging). This script must never hard-fail the pod, so it runs
# without `set -e` and always exits 0.
# ---------------------------------------------------------------------------- #
set +e

log() { echo "[cluster] $*"; }

PROM_CONFIG=/etc/prometheus/prometheus.yml
SUPERVISOR_CONF=/etc/supervisor/supervisord.conf

is_head_node() { [[ "$(hostname -s)" == "node-0" ]]; }

# Build /etc/prometheus/prometheus.yml with one node_exporter (:9100) and one
# dcgm-exporter (:9400) target per peer. Peers are every hostname in /etc/hosts
# that starts with "node-"; falls back to localhost when none are present.
render_prometheus_config() {
    local nodes
    nodes=$(awk '{for (i = 2; i <= NF; i++) if ($i ~ /^node-/) print $i}' /etc/hosts | sort -u)
    if [[ -z "$nodes" ]]; then
        log "no node-* entries in /etc/hosts; scraping localhost only"
        nodes=$(hostname -s)
    fi
    log "prometheus scrape targets: $(echo "$nodes" | tr '\n' ' ')"

    {
        echo "global:"
        echo "  scrape_interval: 15s"
        echo "  evaluation_interval: 15s"
        echo ""
        echo "scrape_configs:"
        echo "  - job_name: node"
        echo "    static_configs:"
        echo "      - targets:"
        for n in $nodes; do echo "          - '${n}:9100'"; done
        echo "  - job_name: dcgm"
        echo "    static_configs:"
        echo "      - targets:"
        for n in $nodes; do echo "          - '${n}:9400'"; done
    } > "$PROM_CONFIG"
}

# Render the scrape config before supervisord starts so Prometheus has it ready.
if is_head_node; then
    log "hostname is node-0 (head node): rendering Prometheus config"
    render_prometheus_config

    # Behind the Runpod proxy the browser origin is
    # <pod-id>-8889.proxy.runpod.net, which Grafana's CSRF check must trust or
    # datasource queries fail with "origin not allowed". Derive it from the pod
    # id and export before supervisord starts so Grafana inherits it.
    if [[ -n "${RUNPOD_POD_ID:-}" ]]; then
        # Proxy base domain — override with RUNPOD_PROXY_BASE for dev pods
        # (e.g. dev-proxy.runpod.net). Defaults to the production proxy.
        proxy_base="${RUNPOD_PROXY_BASE:-proxy.runpod.net}"
        grafana_host="${RUNPOD_POD_ID}-8889.${proxy_base}"
        export GF_SERVER_ROOT_URL="https://${grafana_host}/"
        export GF_SECURITY_CSRF_TRUSTED_ORIGINS="${grafana_host}"
        log "grafana root_url = https://${grafana_host}/"
    fi

    # No admin/admin: give the built-in admin account a random password so it
    # can't be used. Combined with disable_login_form + disabled basic auth
    # (grafana.ini), the ONLY way in is the auth proxy.
    GF_SECURITY_ADMIN_PASSWORD="$(openssl rand -base64 24 2>/dev/null || head -c 18 /dev/urandom | base64)"
    export GF_SECURITY_ADMIN_PASSWORD
    
    # Auto-login is handled by the grafana-proxy: it checks ?token= against the
    # shared secret JUPYTER_PASSWORD (reused from Jupyter) and injects the
    # auth.proxy identity header. Nothing to set up here.
fi

# Start supervisord (daemonizes, then returns). Brings up the autostart=true
# exporters on every node.
if supervisorctl status >/dev/null 2>&1; then
    log "supervisord already running"
else
    log "starting supervisord"
    supervisord -c "$SUPERVISOR_CONF"
    # Wait for the control socket to come up before issuing commands.
    for _ in {1..10}; do
        supervisorctl status >/dev/null 2>&1 && break
        sleep 1
    done
fi

# Head-node only: start the (autostart=false) Loki + Prometheus + Grafana
# programs. Loki starts first so the log store is up before Grafana's datasource
# health check (harmless either way — Grafana retries). The Alloy shippers on
# every node (autostart=true) push to node-0:3100 and retry until Loki is ready.
if is_head_node; then
    log "starting Loki + Prometheus + Grafana + grafana-proxy"
    supervisorctl start loki prometheus grafana grafana-proxy
else
    log "not the head node; Loki/Prometheus/Grafana stay stopped"
fi

log "post-start complete"
exit 0
