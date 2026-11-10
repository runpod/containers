#!/usr/bin/env python3
"""Tiny shared-token reverse proxy in front of Grafana — mirrors Jupyter's model.

Jupyter (container-template/start.sh) takes a shared secret from the env var
$JUPYTER_PASSWORD, passes it as its token, and the console opens
`...-8888.proxy.runpod.net/lab?token=<JUPYTER_PASSWORD>`. This reuses that SAME
secret for Grafana:

  1. Read the token from ?token=, else the session cookie.
  2. Constant-time compare the token to JUPYTER_PASSWORD (or GRAFANA_PASSWORD
     if set, for a Grafana-specific override) and GRAFANA_CLUSTER_TOKEN, or the
     cookie to this process's random session value.
  3. On match -> proxy to Grafana (loopback :3300) injecting the auth.proxy
     identity header (X-WEBAUTH-User); a valid ?token= also sets the HttpOnly
     session cookie so the browser SPA's later (token-less) requests stay
     authenticated. The cookie never holds the secret, and a proxy restart
     ends every session (the stale cookie is purged; ?token= signs in again).
  4. No match / no secret set -> no header -> Grafana shows its login form.

Client-supplied X-WEBAUTH-* is stripped so the identity can't be spoofed, and
Grafana binds loopback so nothing can reach it except this proxy.

Env (all optional):
  JUPYTER_PASSWORD    the shared token (reused from Jupyter)
  GRAFANA_PASSWORD    optional override for a Grafana-specific token
  GRAFANA_CLUSTER_TOKEN
                      a second accepted token, alongside the one above (the
                      ray-cluster head sets it to the Ray cluster token, so
                      the dashboard's link signs Grafana in while the
                      console's JUPYTER_PASSWORD link keeps working)
  PROXY_LISTEN_PORT   default 8889 (the public port Runpod maps)
  GRAFANA_UPSTREAM    default 127.0.0.1:3300
  GRAFANA_PROXY_USER  Grafana username to log in as (default: runpod)
  AUTH_COOKIE         cookie name (default: cluster_auth)
  LOGIN_RETURN_URL    when set, GET /runpod-login?token= sets the session
                      cookie (on a valid token) and redirects here, so another
                      service's login can sign Grafana in on the way (the
                      ray-cluster dashboard does, for its embedded panels).
                      Fixed by the image, never taken from the request, so it
                      can't be an open redirect.
"""
import hmac
import http.client
import http.server
import os
import secrets
import socketserver
import urllib.parse

LISTEN = int(os.environ.get("PROXY_LISTEN_PORT", "8889"))
UPSTREAM = os.environ.get("GRAFANA_UPSTREAM", "127.0.0.1:3300")
# Reuse Jupyter's shared secret; GRAFANA_PASSWORD overrides it if set.
SECRETS = [
    s.encode()
    for s in (
        os.environ.get("GRAFANA_PASSWORD") or os.environ.get("JUPYTER_PASSWORD", ""),
        os.environ.get("GRAFANA_CLUSTER_TOKEN", ""),
    )
    if s
]
USER = os.environ.get("GRAFANA_PROXY_USER", "runpod")
COOKIE = os.environ.get("AUTH_COOKIE", "cluster_auth")
LOGIN_PATH = "/runpod-login"
LOGIN_RETURN_URL = os.environ.get("LOGIN_RETURN_URL", "")

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
    # Bytes, so a non-ASCII token is a mismatch rather than a TypeError.
    token = (token or "").encode()
    return bool(token) and any([hmac.compare_digest(token, s) for s in SECRETS])


SESSION = secrets.token_urlsafe(32)
SESSION_COOKIE = f"{COOKIE}={SESSION}; Path=/; HttpOnly; Secure; SameSite=Lax"


def session_ok(cookie):
    return bool(cookie) and hmac.compare_digest(cookie, SESSION)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _login(self, token):
        # Back to LOGIN_RETURN_URL even on a bad token: that service shows its
        # own prompt, and Grafana its login wall when next opened.
        self.send_response(302)
        self.send_header("Location", LOGIN_RETURN_URL)
        if token_ok(token):
            self.send_header("Set-Cookie", SESSION_COOKIE)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self):
        url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(url.query)
        url_token = params.get("token", [None])[0]
        if LOGIN_RETURN_URL and self.command == "GET" and url.path == LOGIN_PATH:
            self._login(url_token)
            return
        from_url = url_token is not None
        cookie = cookie_value(self.headers.get("Cookie"), COOKIE)
        had_cookie = cookie is not None
        ok = token_ok(url_token) if url_token else session_ok(cookie)

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
            self.send_header("Set-Cookie", SESSION_COOKIE)
        elif not ok and (had_cookie or resp.status == 401):
            # Stale/invalid session cookie (proxy restarted, or a secret-bearing
            # cookie from an older image) -> purge it so the browser stops
            # looping and the ?token= flow can recover.
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
