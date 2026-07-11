#!/usr/bin/env python3
"""Tiny shared-token reverse proxy in front of Grafana — mirrors Jupyter's model.

Jupyter (container-template/start.sh) takes a shared secret from the env var
$JUPYTER_PASSWORD, passes it as its token, and the console opens
`...-8888.proxy.runpod.net/lab?token=<JUPYTER_PASSWORD>`. This reuses that SAME
secret for Grafana:

  1. Read the token from ?token= (or the session cookie).
  2. Constant-time compare it to JUPYTER_PASSWORD (or GRAFANA_PASSWORD if set,
     for a Grafana-specific override).
  3. On match -> proxy to Grafana (loopback :3300) injecting the auth.proxy
     identity header (X-WEBAUTH-User) and set an HttpOnly cookie so the browser
     SPA's later (token-less) requests stay authenticated.
  4. No match / no secret set -> no header -> Grafana shows its login form.

Client-supplied X-WEBAUTH-* is stripped so the identity can't be spoofed, and
Grafana binds loopback so nothing can reach it except this proxy.

Env (all optional):
  JUPYTER_PASSWORD    the shared token (reused from Jupyter)
  GRAFANA_PASSWORD    optional override for a Grafana-specific token
  PROXY_LISTEN_PORT   default 8889 (the public port Runpod maps)
  GRAFANA_UPSTREAM    default 127.0.0.1:3300
  GRAFANA_PROXY_USER  Grafana username to log in as (default: runpod)
  AUTH_COOKIE         cookie name (default: cluster_auth)
"""
import hmac
import http.client
import http.server
import os
import socketserver
import urllib.parse

LISTEN = int(os.environ.get("PROXY_LISTEN_PORT", "8889"))
UPSTREAM = os.environ.get("GRAFANA_UPSTREAM", "127.0.0.1:3300")
# Reuse Jupyter's shared secret; GRAFANA_PASSWORD overrides it if set.
SECRET = os.environ.get("GRAFANA_PASSWORD") or os.environ.get("JUPYTER_PASSWORD", "")
USER = os.environ.get("GRAFANA_PROXY_USER", "runpod")
COOKIE = os.environ.get("AUTH_COOKIE", "cluster_auth")

# Hop-by-hop headers plus ones we set/strip ourselves.
DROP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "x-webauth-user", "x-webauth-email", "x-webauth-name", "x-forwarded-for",
}


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

    def _proxy(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url_token = params.get("token", [None])[0]
        from_url = url_token is not None
        cookie_token = cookie_value(self.headers.get("Cookie"), COOKIE)
        had_cookie = cookie_token is not None
        token = url_token or cookie_token
        ok = token_ok(token)

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https"
        if ok:
            headers["X-WEBAUTH-User"] = USER

        host, _, port = UPSTREAM.partition(":")
        try:
            conn = http.client.HTTPConnection(host, int(port or 80), timeout=60)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except OSError:
            self.send_error(502, "Grafana upstream unavailable")
            return

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in DROP:
                continue
            self.send_header(k, v)
        if ok and from_url:
            # Fresh valid token in the URL -> (re)establish the session cookie.
            self.send_header(
                "Set-Cookie",
                f"{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Lax",
            )
        elif not ok and (had_cookie or resp.status == 401):
            # Stale/invalid token cookie (e.g. secret rotated on redeploy) -> purge
            # it so the browser stops looping and the ?token= flow can recover.
            self.send_header(
                "Set-Cookie",
                f"{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
            )
        if resp.status == 401:
            # Also drop any stale Grafana session cookie from a previous deploy
            # that would otherwise keep 401-ing (login form is disabled).
            self.send_header(
                "Set-Cookie",
                "grafana_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
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
    Server(("0.0.0.0", LISTEN), Handler).serve_forever()
