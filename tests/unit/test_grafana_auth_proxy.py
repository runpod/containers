"""The pytorch-cluster Grafana token proxy (config/grafana-proxy/auth_proxy.py).

Runs the real proxy on a loopback port in front of a fake Grafana that records
each request, and checks who gets the auth.proxy identity header, what the
session cookie holds, and the /runpod-login bounce the ray-cluster dashboard
uses. The proxy reads its env at import, so each case loads its own copy.
"""

import http.client
import http.server
import importlib.util
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY = REPO_ROOT / "official-templates/pytorch-cluster/config/grafana-proxy/auth_proxy.py"

JUPYTER = "jupyter-secret"
CLUSTER = "cluster-token"
RETURN_URL = "https://abc123-8266.proxy.runpod.net/"


class FakeGrafana(http.server.BaseHTTPRequestHandler):
    """Answers 200, or 401 without the identity header, and records the request."""

    seen = []

    def do_GET(self):
        FakeGrafana.seen.append((self.path, self.headers.get("X-WEBAUTH-User")))
        self.send_response(200 if self.headers.get("X-WEBAUTH-User") else 401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET

    def log_message(self, *args):
        pass


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ProxyTest(unittest.TestCase):
    env = {"JUPYTER_PASSWORD": JUPYTER, "GRAFANA_CLUSTER_TOKEN": CLUSTER}

    def setUp(self):
        upstream = serve(http.server.HTTPServer(("127.0.0.1", 0), FakeGrafana))
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        FakeGrafana.seen = []

        env = {"GRAFANA_UPSTREAM": f"127.0.0.1:{upstream.server_port}", **self.env}
        spec = importlib.util.spec_from_file_location("auth_proxy", PROXY)
        self.proxy = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, env, clear=True):
            spec.loader.exec_module(self.proxy)
        server = serve(self.proxy.Server(("127.0.0.1", 0), self.proxy.Handler))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port

    def get(self, path, cookie=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request(method, path, headers={"Cookie": cookie} if cookie else {})
        resp = conn.getresponse()
        resp.read()
        return resp

    def session_cookie(self, resp):
        """The cluster_auth value the response sets, or None."""
        for value in resp.headers.get_all("Set-Cookie") or []:
            if value.startswith("cluster_auth=") and "Max-Age=0" not in value:
                return value.split(";")[0]
        return None


class Tokens(ProxyTest):
    def test_either_token_signs_in(self):
        for token in (JUPYTER, CLUSTER):
            with self.subTest(token=token):
                resp = self.get(f"/?token={token}")
                self.assertEqual(resp.status, 200)
                self.assertIsNotNone(self.session_cookie(resp))

    def test_wrong_or_missing_token_gets_no_identity(self):
        for path in ("/?token=wrong", "/?token=%C3%A9", "/"):
            with self.subTest(path=path):
                resp = self.get(path)
                self.assertEqual(resp.status, 401)
                self.assertIsNone(self.session_cookie(resp))
        self.assertEqual({user for _, user in FakeGrafana.seen}, {None})

    def test_cookie_is_a_session_not_the_secret(self):
        cookie = self.session_cookie(self.get(f"/?token={CLUSTER}"))
        value = cookie.partition("=")[2]
        self.assertNotIn(value, (JUPYTER, CLUSTER))
        self.assertEqual(self.get("/d-solo/x", cookie=cookie).status, 200)

    def test_secret_as_cookie_is_refused(self):
        # A cookie from an older image held the token itself.
        resp = self.get("/", cookie=f"cluster_auth={JUPYTER}")
        self.assertEqual(resp.status, 401)
        purged = resp.headers.get_all("Set-Cookie")
        self.assertTrue(any(v.startswith("cluster_auth=;") for v in purged), purged)

    def test_non_ascii_cookie_is_refused(self):
        # Header bytes decode as latin-1; this used to raise in compare_digest.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.putrequest("GET", "/")
        conn.putheader("Cookie", "cluster_auth=\xe9".encode("latin-1"))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 401)

    def test_client_identity_header_is_stripped(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", "/", headers={"X-WEBAUTH-User": "admin"})
        self.assertEqual(conn.getresponse().status, 401)


class NoSecret(ProxyTest):
    env = {}

    def test_fails_closed(self):
        self.assertEqual(self.get("/?token=").status, 401)
        self.assertEqual(self.get("/?token=anything").status, 401)


class Login(ProxyTest):
    env = {**ProxyTest.env, "LOGIN_RETURN_URL": RETURN_URL}

    def test_valid_token_sets_cookie_and_returns(self):
        resp = self.get(f"/runpod-login?token={CLUSTER}")
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers["Location"], RETURN_URL)
        cookie = self.session_cookie(resp)
        self.assertIsNotNone(cookie)
        self.assertNotIn(cookie.partition("=")[2], (JUPYTER, CLUSTER))
        self.assertEqual(FakeGrafana.seen, [])

    def test_bad_token_returns_without_cookie(self):
        for path in ("/runpod-login?token=wrong", "/runpod-login"):
            with self.subTest(path=path):
                resp = self.get(path)
                self.assertEqual(resp.status, 302)
                self.assertEqual(resp.headers["Location"], RETURN_URL)
                self.assertIsNone(self.session_cookie(resp))

    def test_return_url_is_not_taken_from_the_request(self):
        resp = self.get(f"/runpod-login?token={CLUSTER}&next=https://evil.example/")
        self.assertEqual(resp.headers["Location"], RETURN_URL)

    def test_post_is_proxied(self):
        self.get("/runpod-login", method="POST")
        self.assertEqual([path for path, _ in FakeGrafana.seen], ["/runpod-login"])


class NoLogin(ProxyTest):
    def test_login_path_is_proxied(self):
        resp = self.get(f"/runpod-login?token={CLUSTER}")
        self.assertEqual(resp.status, 200)
        self.assertEqual(FakeGrafana.seen, [(f"/runpod-login?token={CLUSTER}", "runpod")])


if __name__ == "__main__":
    unittest.main()
