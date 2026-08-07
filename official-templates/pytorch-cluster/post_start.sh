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

# Head-node only: bring up the MariaDB backend for Slurm job accounting and make
# sure the accounting database + user exist. slurmdbd (provisioned at runtime by
# Runpod, or configured separately) creates and owns the accounting *tables* on
# first connect — this only prepares the empty database + a user it can log in
# as. All steps are idempotent (safe on every boot) and never hard-fail the pod.
#
# The datadir lives on the /workspace persistent volume but is scoped by node-0's
# pod id: /workspace/slurm-acct-db/$RUNPOD_POD_ID. RunPod exposes no stable
# per-cluster id, and two clusters can share one /workspace network volume — a
# per-instance path stops two mariadbd from opening one InnoDB datadir (which
# corrupts it). Trade-off: the pod id changes on cluster recreation, so
# accounting history does NOT carry over; each cluster instance gets a fresh
# datadir, and stale per-instance dirs can be pruned from the volume by hand.
bootstrap_slurm_acct_db() {
    local instance="${RUNPOD_POD_ID:-$(hostname -s)}"
    local datadir="/workspace/slurm-acct-db/${instance}"
    local dbname="${SLURM_ACCT_DB_NAME:-slurm_acct_db}"
    local dbuser="${SLURM_ACCT_DB_USER:-slurm}"
    # slurmdbd.conf's StoragePass must match this; override both together.
    local dbpass="${SLURM_ACCT_DB_PASSWORD:-slurm}"

    # Fail loudly (not with a cryptic supervisor "spawn error") if MariaDB isn't
    # actually in this image — e.g. running an old image whose apt layer predates
    # the mariadb-server addition.
    if [[ ! -x /usr/sbin/mariadbd ]] || ! command -v mariadb-install-db >/dev/null 2>&1; then
        log "WARNING: MariaDB not installed (/usr/sbin/mariadbd or mariadb-install-db missing);"
        log "         skipping accounting DB setup. Rebuild the image so mariadb-server is present."
        return 0
    fi

    mkdir -p "$datadir" /run/mysqld

    # /workspace is a RunPod network volume that often forbids chown (root is
    # squashed / ownership changes return EPERM). Try to hand the datadir to the
    # mysql user; if that fails, run mariadbd as root so it matches whatever uid
    # actually owns the volume. /run/mysqld is local and always chown-able.
    local run_user=mysql
    if ! chown -R mysql:mysql "$datadir" 2>/dev/null; then
        log "cannot chown $datadir (network volume?) — MariaDB will run as root"
        run_user=root
    fi
    chown mysql:mysql /run/mysqld 2>/dev/null || true

    # Render the datadir + resolved run-user into a MariaDB include. It sorts
    # after the baked 99-slurm-acct.cnf (zz- > 99-), so these win; mariadbd and
    # mariadb-install-db both read it.
    cat > /etc/mysql/mariadb.conf.d/zz-slurm-acct-datadir.cnf <<CNF
[mysqld]
datadir = ${datadir}
user = ${run_user}
CNF

    # Initialise the datadir on first boot (empty volume). Detect via the mysql
    # system schema directory; skip on later boots so existing data is kept.
    # Keep the log (not /dev/null) so a failed init is diagnosable.
    if [[ ! -d "$datadir/mysql" ]]; then
        # No system schema => fresh or previously-failed datadir. Clear any
        # partial leftovers (e.g. ibdata1 from a failed attempt) so install-db
        # starts clean.
        find "$datadir" -mindepth 1 -delete 2>/dev/null || true
        log "initialising MariaDB data directory at $datadir (user=$run_user)"
        if ! mariadb-install-db --user="$run_user" --datadir="$datadir" --skip-test-db \
                >/var/log/supervisor/mariadb-install.log 2>&1; then
            log "WARNING: mariadb-install-db failed (see /var/log/supervisor/mariadb-install.log);"
            log "         skipping accounting DB setup"
            return 0
        fi
    else
        log "MariaDB data directory already initialised at $datadir"
    fi

    log "starting MariaDB (datadir=$datadir)"
    supervisorctl start mariadb

    # Wait for the server socket before issuing SQL (root connects via the local
    # unix socket as the OS root user — no password needed).
    local up=""
    for _ in {1..30}; do
        if mysqladmin --protocol=socket ping >/dev/null 2>&1; then up=1; break; fi
        sleep 1
    done
    if [[ -z "$up" ]]; then
        log "WARNING: MariaDB did not become ready; skipping accounting DB bootstrap"
        log "         supervisor status: $(supervisorctl status mariadb 2>&1)"
        [[ -f /var/log/supervisor/mariadb.err ]] && \
            log "         mariadb.err tail: $(tail -n 3 /var/log/supervisor/mariadb.err 2>/dev/null | tr '\n' '|')"
        return 0
    fi

    log "ensuring Slurm accounting database '${dbname}' and user '${dbuser}'@'localhost'"
    mariadb -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${dbname}\`;
CREATE USER IF NOT EXISTS '${dbuser}'@'localhost' IDENTIFIED BY '${dbpass}';
ALTER USER '${dbuser}'@'localhost' IDENTIFIED BY '${dbpass}';
GRANT ALL PRIVILEGES ON \`${dbname}\`.* TO '${dbuser}'@'localhost';
FLUSH PRIVILEGES;
SQL
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

    # MariaDB backend for Slurm job accounting (initialises the datadir on
    # /workspace, starts mariadbd, and ensures the accounting DB + user exist).
    bootstrap_slurm_acct_db
else
    log "not the head node; Loki/Prometheus/Grafana/MariaDB stay stopped"
fi

log "post-start complete"
exit 0
