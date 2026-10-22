#!/usr/bin/env python3
"""Shared-token reverse proxy in front of the Ray dashboard — fail-closed.

Same model as the Grafana proxy in the pytorch-cluster base (auth_proxy.py)
and Jupyter itself: the Runpod proxy serves mapped ports publicly, so the pod
carries its own credential. The console hands the operator the token in the
URL; a cookie keeps the SPA's later (token-less) requests authenticated.

The difference from Grafana is the failure mode. Grafana has its own login
form to pass through to; the Ray dashboard has NO authentication at all and
its API submits arbitrary jobs (this is ShadowRay, CVE-2023-48022). So this
proxy never forwards an unauthenticated request upstream: no valid token, or
no secret configured at all, gets a 403 and nothing more.

The dashboard itself keeps binding 0.0.0.0:8265 — the host daemon's readiness
poll (pkg/rayready) reaches it on the docker bridge, which is why 8265 stays
unmapped but live. This proxy listens on 8266, the one dashboard port that is
safe to expose through Runpod's proxy.

WebSocket upgrades are not proxied (the upgrade header is dropped); the
dashboard's log views degrade to polling. Everything else — the SPA, the REST
and State APIs — passes through verbatim.

Env (all optional):
  JUPYTER_PASSWORD         the shared token (reused from Jupyter, as Grafana's)
  RAY_DASHBOARD_PASSWORD   optional override for a dashboard-specific token
  PROXY_LISTEN_PORT        default 8266 (the public port to map)
  RAY_DASHBOARD_UPSTREAM   default 127.0.0.1:8265
  AUTH_COOKIE              cookie name (default: ray_dashboard_auth)
"""
import hmac
import http.client
import http.server
import os
import socketserver
import sys
import urllib.parse

LISTEN = int(os.environ.get("PROXY_LISTEN_PORT", "8266"))
UPSTREAM = os.environ.get("RAY_DASHBOARD_UPSTREAM", "127.0.0.1:8265")
# Reuse Jupyter's shared secret, as the Grafana proxy does; the override names
# a dashboard-specific token.
SECRET = os.environ.get("RAY_DASHBOARD_PASSWORD") or os.environ.get("JUPYTER_PASSWORD", "")
COOKIE = os.environ.get("AUTH_COOKIE", "ray_dashboard_auth")

# Hop-by-hop headers plus the auth cookie is intentionally forwarded: the
# dashboard ignores cookies, and the token is checked before anything is
# proxied, so there is nothing to spoof.
DROP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "x-forwarded-for",
}

DENY_BODY = (
    b"Forbidden. This proxy gates the Ray dashboard, which has no "
    b"authentication of its own (open it once with "
    b"?token=<RAY_DASHBOARD_PASSWORD or JUPYTER_PASSWORD>; a cookie keeps the "
    b"session)."
)
NO_SECRET_BODY = (
    b"Forbidden. Neither RAY_DASHBOARD_PASSWORD nor JUPYTER_PASSWORD is set, "
    b"so this proxy refuses all traffic rather than expose the unauthenticated "
    b"Ray dashboard."
)


def cookie_value(header, name):
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def token_ok(token):
    return bool(SECRET) and bool(token) and hmac.compare_digest(token, SECRET)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _deny(self, body, had_cookie):
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if had_cookie:
            # Stale/invalid token cookie (e.g. secret rotated on redeploy) ->
            # purge it so the ?token= flow can recover.
            self.send_header(
                "Set-Cookie",
                f"{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
            )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url_token = params.get("token", [None])[0]
        from_url = url_token is not None
        cookie_token = cookie_value(self.headers.get("Cookie"), COOKIE)
        had_cookie = cookie_token is not None
        ok = token_ok(url_token or cookie_token)

        # Fail closed: an unauthenticated request never reaches the dashboard.
        if not ok:
            self._deny(DENY_BODY if SECRET else NO_SECRET_BODY, had_cookie)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https"

        host, _, port = UPSTREAM.partition(":")
        try:
            conn = http.client.HTTPConnection(host, int(port or 80), timeout=60)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except OSError:
            self.send_error(502, "Ray dashboard upstream unavailable")
            return

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in DROP:
                continue
            self.send_header(k, v)
        if from_url:
            # Fresh valid token in the URL -> (re)establish the session cookie.
            self.send_header(
                "Set-Cookie",
                f"{COOKIE}={url_token}; Path=/; HttpOnly; Secure; SameSite=Lax",
            )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _proxy

    def log_message(self, *args):
        pass  # quiet; supervisord captures stderr


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    if SECRET:
        source = "RAY_DASHBOARD_PASSWORD" if os.environ.get("RAY_DASHBOARD_PASSWORD") else "JUPYTER_PASSWORD"
        print(f"ray-dashboard-proxy: listening on :{LISTEN} -> {UPSTREAM}, token from {source}", file=sys.stderr)
    else:
        print(
            "ray-dashboard-proxy: WARNING: no RAY_DASHBOARD_PASSWORD or JUPYTER_PASSWORD set; "
            "every request will be refused (fail-closed)",
            file=sys.stderr,
        )
    Server(("0.0.0.0", LISTEN), Handler).serve_forever()
