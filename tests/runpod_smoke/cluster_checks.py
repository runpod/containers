"""Checks specific to the pytorch-cluster image on an Instant Cluster.

  * node_identity_command — the node's hostname matches its cluster rank;
    post_start.sh decides head vs worker from `hostname -s == node-0`
  * head_monitoring_command — on node-0: every supervisord program RUNNING,
    Grafana and Prometheus healthy, and Prometheus scraping node_exporter
    (and dcgm-exporter) on EVERY node — the only signal that proves the
    multi-node wiring rather than one healthy pod
  * worker_monitoring_command — on node-N: exporters up, head-only
    services not running
  * run_grafana_proxy_check — Grafana through the public proxy on :8889:
    health, token login via the auth proxy, refusal without a token, and a
    query through the Prometheus datasource

Shell snippets are built here and run with checks.run_simple_check, like the
hygiene checks.
"""

from __future__ import annotations

import json
import shlex
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config

_UA = "runpod-smoke-test/1.0"

HEAD_ONLY_PROGRAMS = ("prometheus", "grafana", "grafana-proxy")
HEAD_PROGRAMS = ("node_exporter", "dcgm-exporter", *HEAD_ONLY_PROGRAMS)


def _exporters(require_dcgm: bool) -> tuple[str, ...]:
    return ("node_exporter", "dcgm-exporter") if require_dcgm else ("node_exporter",)


def node_identity_command(idx: int) -> str:
    """The hostname must be `node-<idx>`: the image keys every head-only
    service off `node-0`, so a mismatch silently yields a cluster with no
    Grafana, or two of them."""
    want = f"node-{idx}"
    return (
        "HN=$(hostname -s); "
        "echo \"hostname: $HN\"; "
        "echo \"node-* in /etc/hosts: $(awk '{for (i = 2; i <= NF; i++) "
        "if ($i ~ /^node-/) print $i}' /etc/hosts | sort -u | tr '\\n' ' ')\"; "
        f"[ \"$HN\" = {shlex.quote(want)} ] "
        f"|| {{ echo 'FAIL: expected hostname {want} for cluster rank {idx}'; "
        "exit 1; }"
    )


def _supervisor_wait_snippet(programs: tuple[str, ...], timeout: int) -> str:
    """Wait for each program to reach RUNNING; print status either way."""
    names = " ".join(programs)
    return (
        f"for i in $(seq 1 {timeout}); do "
        "  MISSING=''; "
        f"  for p in {names}; do "
        "    supervisorctl status \"$p\" 2>/dev/null | grep -q RUNNING "
        "      || MISSING=\"$MISSING $p\"; "
        "  done; "
        "  [ -z \"$MISSING\" ] && break; "
        "  sleep 1; "
        "done; "
        "echo '--- supervisorctl status ---'; "
        "supervisorctl status 2>&1; "
        "[ -z \"$MISSING\" ] "
        f"|| {{ echo \"FAIL: not RUNNING after {timeout}s:$MISSING\"; exit 1; }}; "
    )


# Polls /api/v1/targets until every expected job reports `want` healthy
# targets, then prints one line per target. argv: want, timeout, jobs...
_TARGETS_PROGRAM = r"""
import json, sys, time, urllib.request
want, timeout, jobs = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
deadline = time.time() + timeout
url = 'http://127.0.0.1:9090/api/v1/targets?state=active'
targets, err = [], ''


def healthy(job):
    return sum(
        1 for t in targets
        if t['labels'].get('job') == job and t.get('health') == 'up'
    )


while True:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            targets = json.load(r)['data']['activeTargets']
        err = ''
    except Exception as e:
        err = f'{type(e).__name__}: {e}'
    up = {j: healthy(j) for j in jobs}
    if not err and all(up[j] >= want for j in jobs):
        break
    if time.time() >= deadline:
        break
    time.sleep(5)
print('--- prometheus targets ---')
order = lambda t: (t['labels'].get('job', ''), t['labels'].get('instance', ''))
for t in sorted(targets, key=order):
    line = f"{t['labels'].get('job')} {t['labels'].get('instance')} {t.get('health')}"
    if t.get('lastError'):
        line += f" ({t['lastError'][:120]})"
    print(line)
if err:
    print(f'FAIL: Prometheus targets API unreachable: {err}')
    sys.exit(1)
short = [f'{j} {up[j]}/{want}' for j in jobs if up[j] < want]
if short:
    print(f'FAIL: Prometheus is not scraping every node: ' + ', '.join(short))
    sys.exit(1)
print('targets OK: ' + ', '.join(f'{j} {up[j]}/{want}' for j in jobs))
"""


def head_monitoring_command(
    node_count: int, timeout: int, require_dcgm: bool = True,
) -> str:
    """Run on node-0. Everything the Grafana dashboards depend on."""
    programs = HEAD_PROGRAMS if require_dcgm else tuple(
        p for p in HEAD_PROGRAMS if p != "dcgm-exporter"
    )
    jobs = ["node", "dcgm"] if require_dcgm else ["node"]
    curl = "curl -sS --max-time 5"
    return (
        "set -u; "
        + _supervisor_wait_snippet(programs, timeout)
        + "echo '--- grafana /api/health (loopback :3300) ---'; "
        f"for i in $(seq 1 {timeout}); do "
        f"  OUT=$({curl} http://127.0.0.1:3300/api/health 2>&1) && break; "
        "  sleep 1; "
        "done; "
        "echo \"$OUT\"; "
        "echo \"$OUT\" | grep -q '\"database\": *\"ok\"' "
        "|| { echo 'FAIL: Grafana /api/health not ok'; exit 1; }; "
        "echo '--- auth proxy (loopback :8889) ---'; "
        f"CODE=$({curl} -o /dev/null -w '%{{http_code}}' "
        f"http://127.0.0.1:{config.GRAFANA_PORT}/api/health || echo none); "
        "echo \"http=$CODE\"; "
        "[ \"$CODE\" = 200 ] || { echo 'FAIL: grafana-proxy not answering'; exit 1; }; "
        "echo '--- prometheus /-/ready ---'; "
        f"{curl} http://127.0.0.1:9090/-/ready "
        "|| { echo 'FAIL: Prometheus not ready'; exit 1; }; echo; "
        "echo '--- /etc/prometheus/prometheus.yml targets ---'; "
        "grep -E \"^ *- '\" /etc/prometheus/prometheus.yml; "
        f"python3 -c {shlex.quote(_TARGETS_PROGRAM)} "
        f"{node_count} {timeout} {' '.join(jobs)}"
    )


def worker_monitoring_command(timeout: int, require_dcgm: bool = True) -> str:
    """Run on node-N (N > 0): exporters up, head-only services stopped."""
    head_only = " ".join(HEAD_ONLY_PROGRAMS)
    return (
        "set -u; "
        + _supervisor_wait_snippet(_exporters(require_dcgm), timeout)
        + "EXTRA=''; "
        f"for p in {head_only}; do "
        "  supervisorctl status \"$p\" 2>/dev/null | grep -q RUNNING "
        "    && EXTRA=\"$EXTRA $p\"; "
        "done; "
        "[ -z \"$EXTRA\" ] "
        "|| { echo \"FAIL: head-only services running on a worker:$EXTRA\"; exit 1; }; "
        "echo 'worker monitoring OK'"
    )


# ---------------------------------------------------------------------------
# Grafana through the public proxy
# ---------------------------------------------------------------------------


def _get(url: str, timeout: int = 15) -> tuple[int, str]:
    """GET returning (status, body). Status 0 is a transport failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(1024).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — body is best-effort
            body = ""
        return exc.code, body
    except OSError as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def _json(body: str) -> Optional[dict]:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def run_grafana_proxy_check(pod_id: str) -> tuple[bool, str]:
    """Grafana on the head node, from the outside, the way a user gets it.

    1. `/api/health` answers 200 with a healthy database — retried, since
       the proxy registers a fresh port and Grafana boots after sshd.
    2. `/api/user?token=<JUPYTER_PASSWORD>` logs in as the auth-proxy user:
       proves the proxy's shared-token model end to end.
    3. `/api/user` without a token is refused: Grafana must never be open.
    4. A query through the provisioned Prometheus datasource succeeds: the
       dashboards render data, not just an empty shell.
    """
    base = config.proxy_url(pod_id, config.GRAFANA_PORT)
    token = config.JUPYTER_TEST_PASSWORD
    lines = [f"Grafana via {base}"]

    deadline = time.monotonic() + config.GRAFANA_PROXY_TIMEOUT
    attempt, code, body = 0, 0, ""
    while True:
        attempt += 1
        code, body = _get(f"{base}/api/health")
        health = _json(body) if code == 200 else None
        if health and health.get("database") == "ok":
            lines.append(
                f"GET /api/health: HTTP 200 (attempt #{attempt}) {body.strip()[:160]}"
            )
            break
        if time.monotonic() >= deadline:
            lines.append(
                f"FAIL: /api/health not ok after {config.GRAFANA_PROXY_TIMEOUT}s "
                f"({attempt} attempts), last: HTTP {code} {body.strip()[:160]}"
            )
            return False, "\n".join(lines)
        time.sleep(5)

    code, body = _get(f"{base}/api/user?token={token}")
    user = _json(body) if code == 200 else None
    login = (user or {}).get("login")
    lines.append(f"GET /api/user?token=<redacted>: HTTP {code} login={login!r}")
    if not login:
        lines.append(
            "FAIL: the shared token did not log in through the auth proxy "
            f"({body.strip()[:160]})"
        )
        return False, "\n".join(lines)

    code, body = _get(f"{base}/api/user")
    lines.append(f"GET /api/user (no token): HTTP {code}")
    if code == 200:
        lines.append(
            "FAIL: Grafana answered /api/user without a token — not protected"
        )
        return False, "\n".join(lines)

    code, body = _get(
        f"{base}/api/datasources/proxy/uid/prometheus/api/v1/query"
        f"?query=up&token={token}"
    )
    result = _json(body) if code == 200 else None
    series = ((result or {}).get("data") or {}).get("result") or []
    lines.append(
        f"GET datasource prometheus query=up: HTTP {code} series={len(series)}"
    )
    if (result or {}).get("status") != "success" or not series:
        lines.append(
            "FAIL: Grafana could not query its Prometheus datasource "
            f"({body.strip()[:160]})"
        )
        return False, "\n".join(lines)
    lines.append("grafana check OK")
    return True, "\n".join(lines)
