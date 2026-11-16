"""The ComfyUI password proxy (official-templates/comfyui/scripts/auth_proxy.py).

Runs the real proxy on a loopback port in front of a fake ComfyUI that records
what reaches it, and checks that nothing gets through without the password,
that the password never reaches ComfyUI, that the UI's websocket works through
it, and that another site cannot drive the pod through a signed-in browser.

The proxy is built on aiohttp, which ComfyUI depends on, so these tests need
it; CI installs it. The proxy reads its env at import, so each case loads its
own copy.
"""

import base64
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

try:
    import aiohttp
    from aiohttp import web
except ImportError:  # pragma: no cover - CI installs aiohttp
    aiohttp = None

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY = REPO_ROOT / "official-templates/comfyui/scripts/auth_proxy.py"
PASSWORD = "correct-horse-battery"

if aiohttp is None and os.environ.get("CI"):
    raise ImportError("aiohttp is required for the ComfyUI proxy tests in CI")


def basic(password, user="anyone"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


BEARER = {"Authorization": f"Bearer {PASSWORD}"}


@unittest.skipIf(aiohttp is None, "aiohttp is not installed")
class ProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        # ComfyUI's own limit (--max-upload-size, 100 MB by default).
        upstream = web.Application(client_max_size=100 * 1024 * 1024)
        upstream.router.add_route("*", "/ws", self.fake_ws)
        upstream.router.add_route("*", "/{tail:.*}", self.fake_http)
        self.upstream_port = await self.serve(upstream)

        env = {
            "COMFYUI_PASSWORD": PASSWORD,
            "COMFYUI_UPSTREAM": f"127.0.0.1:{self.upstream_port}",
        }
        spec = importlib.util.spec_from_file_location("comfyui_auth_proxy", PROXY)
        self.proxy = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, env, clear=True):
            spec.loader.exec_module(self.proxy)
        self.port = await self.serve(self.proxy.make_app())
        self.base = f"http://127.0.0.1:{self.port}"

        self.client = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        self.addAsyncCleanup(self.client.close)

    async def serve(self, app):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.addAsyncCleanup(runner.cleanup)
        return runner.addresses[0][1]

    async def fake_http(self, request):
        body = await request.read()
        self.seen.append({
            "method": request.method,
            "path": request.path_qs,
            "headers": dict(request.headers),
            "body": body,
        })
        if request.path == "/big":
            return web.Response(body=b"x" * (3 * 1024 * 1024))
        response = web.Response(text=f"ok {len(body)}")
        response.headers.add("Set-Cookie", "a=1; Path=/")
        response.headers.add("Set-Cookie", "b=2; Path=/")
        return response

    async def fake_ws(self, request):
        self.seen.append({"path": request.path_qs, "headers": dict(request.headers)})
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str('{"type": "status"}')
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str("echo:" + message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                await ws.send_bytes(b"echo:" + message.data)
        return ws

    async def call(self, method, path, **kwargs):
        kwargs.setdefault("allow_redirects", False)
        async with self.client.request(method, self.base + path, **kwargs) as resp:
            return resp.status, resp.headers, await resp.read()

    # -- nothing gets through without the password ---------------------------

    async def test_post_prompt_without_password_is_401(self):
        status, headers, _ = await self.call("POST", "/prompt", json={"prompt": {}})
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(self.seen, [], "ComfyUI must not see the request")

    async def test_every_path_needs_the_password(self):
        for method, path in [("GET", "/"), ("GET", "/system_stats"),
                             ("GET", "/manager/version"), ("POST", "/manager/reboot"),
                             ("GET", "/api/userdata"), ("OPTIONS", "/prompt")]:
            with self.subTest(path=path):
                status, _, _ = await self.call(method, path)
                self.assertEqual(status, 401)
        self.assertEqual(self.seen, [])

    async def test_wrong_password_is_401(self):
        for headers in (basic("nope"), {"Authorization": "Bearer nope"},
                        {"Authorization": "Basic !!!not-base64"},
                        basic(PASSWORD + "x"), {"Cookie": "comfyui_auth=forged"}):
            with self.subTest(headers=headers):
                status, _, _ = await self.call("GET", "/", headers=headers)
                self.assertEqual(status, 401)
        status, _, _ = await self.call("GET", "/?token=nope")
        self.assertEqual(status, 401)
        self.assertEqual(self.seen, [])

    async def test_websocket_without_password_is_refused(self):
        with self.assertRaises(aiohttp.WSServerHandshakeError) as caught:
            await self.client.ws_connect(self.base + "/ws?clientId=abc")
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(self.seen, [])

    # -- the password gets through, and goes no further -----------------------

    async def test_basic_auth_any_username(self):
        status, headers, body = await self.call(
            "POST", "/prompt", json={"prompt": {}}, headers=basic(PASSWORD, "me"))
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok 14")
        self.assertNotIn("Authorization", self.seen[0]["headers"])
        cookies = headers.getall("Set-Cookie")
        self.assertIn("a=1; Path=/", cookies, "upstream cookies must survive")
        self.assertIn("b=2; Path=/", cookies)
        self.assertTrue(any(c.startswith("comfyui_auth=") for c in cookies))

    async def test_bearer_token(self):
        status, _, _ = await self.call("GET", "/system_stats", headers=BEARER)
        self.assertEqual(status, 200)
        self.assertNotIn("Authorization", self.seen[0]["headers"])

    async def test_session_cookie_signs_in_and_is_not_forwarded(self):
        _, headers, _ = await self.call("GET", "/", headers=BEARER)
        session = next(c for c in headers.getall("Set-Cookie")
                       if c.startswith("comfyui_auth="))
        self.assertIn("HttpOnly", session)
        self.assertIn("SameSite=Lax", session)
        self.assertNotIn(PASSWORD, session, "the cookie must not hold the password")
        cookie = session.split(";")[0]

        status, headers, _ = await self.call(
            "GET", "/queue", headers={"Cookie": f"other=1; {cookie}"})
        self.assertEqual(status, 200)
        self.assertNotIn("comfyui_auth", self.seen[-1]["headers"]["Cookie"])
        self.assertEqual(self.seen[-1]["headers"]["Cookie"], "other=1")
        self.assertFalse(any(c.startswith("comfyui_auth=")
                             for c in headers.getall("Set-Cookie", [])))

    async def test_token_link_redirects_without_the_token(self):
        status, headers, _ = await self.call(
            "GET", "/?token=" + PASSWORD + "&tab=queue",
            headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/?tab=queue")
        self.assertTrue(headers["Set-Cookie"].startswith("comfyui_auth="))
        self.assertEqual(self.seen, [])

    async def test_token_link_cannot_redirect_to_another_site(self):
        """`//evil.example` in a Location header is another site to a browser."""
        for path in ("//evil.example/x", "///evil.example/x"):
            with self.subTest(path=path):
                status, headers, _ = await self.call(
                    "GET", f"{path}?token={PASSWORD}",
                    headers={"Sec-Fetch-Mode": "navigate"})
                self.assertEqual(status, 302)
                self.assertEqual(headers["Location"], "/evil.example/x")

    async def test_token_on_api_call_is_stripped(self):
        status, _, _ = await self.call(
            "GET", f"/view?filename=a%20b.png&token={PASSWORD}&type=output")
        self.assertEqual(status, 200)
        self.assertNotIn(PASSWORD, self.seen[0]["path"])
        self.assertIn("filename=a", self.seen[0]["path"])
        self.assertIn("type=output", self.seen[0]["path"])

    async def test_host_header_is_preserved(self):
        """ComfyUI compares Host with Origin when the Host is loopback; a
        rewritten Host would make it refuse the UI's own POSTs."""
        await self.call("GET", "/", headers={
            **BEARER, "Host": "abc-8188.proxy.runpod.net"})
        self.assertEqual(self.seen[0]["headers"]["Host"], "abc-8188.proxy.runpod.net")

    async def test_large_bodies_stream_both_ways(self):
        payload = os.urandom(5 * 1024 * 1024)
        status, _, body = await self.call(
            "POST", "/upload/image", data=payload, headers=BEARER)
        self.assertEqual(status, 200)
        self.assertEqual(self.seen[0]["body"], payload)
        status, _, body = await self.call("GET", "/big", headers=BEARER)
        self.assertEqual(len(body), 3 * 1024 * 1024)

    async def test_websocket_through_proxy(self):
        ws = await self.client.ws_connect(
            self.base + "/ws?clientId=abc", headers=basic(PASSWORD))
        first = await ws.receive_str(timeout=5)
        self.assertEqual(first, '{"type": "status"}')
        await ws.send_str("hello")
        self.assertEqual(await ws.receive_str(timeout=5), "echo:hello")
        await ws.send_bytes(b"\x00\x01")
        self.assertEqual(await ws.receive_bytes(timeout=5), b"echo:\x00\x01")
        await ws.close()
        self.assertEqual(self.seen[0]["path"], "/ws?clientId=abc")
        self.assertNotIn("Authorization", self.seen[0]["headers"])

    async def test_upstream_down_is_502(self):
        self.proxy.UPSTREAM = "127.0.0.1:1"
        status, _, body = await self.call("GET", "/", headers=BEARER)
        self.assertEqual(status, 502)
        self.assertIn(b"not answering", body)

    # -- password guessing is rate-limited -------------------------------------

    async def throttled_proxy(self, burst=3):
        """A second proxy with a small budget and a clock the test moves."""
        self.now = 1000.0
        budget = self.proxy.FailureBudget(
            burst=burst, per_second=1.0, clock=lambda: self.now)
        port = await self.serve(self.proxy.make_app(budget))
        return f"http://127.0.0.1:{port}"

    async def call_at(self, base, method, path, **kwargs):
        kwargs.setdefault("allow_redirects", False)
        async with self.client.request(method, base + path, **kwargs) as resp:
            return resp.status, resp.headers, await resp.read()

    async def test_wrong_passwords_pause_password_checks(self):
        base = await self.throttled_proxy(burst=3)
        for wrong in (basic("a"), {"Authorization": "Bearer b"}, basic("c")):
            status, _, _ = await self.call_at(base, "GET", "/", headers=wrong)
            self.assertEqual(status, 401)
        # Full: even the right password is not checked, or a guesser would
        # learn from the answer.
        status, headers, _ = await self.call_at(base, "GET", "/", headers=BEARER)
        self.assertEqual(status, 429)
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        status, _, _ = await self.call_at(base, "GET", f"/?token={PASSWORD}")
        self.assertEqual(status, 429)
        self.assertEqual(self.seen, [])
        # One attempt has drained a second later.
        self.now += 1.0
        status, _, _ = await self.call_at(base, "GET", "/", headers=BEARER)
        self.assertEqual(status, 200)

    async def test_signed_in_browser_is_not_throttled(self):
        base = await self.throttled_proxy(burst=1)
        _, headers, _ = await self.call_at(base, "GET", "/", headers=BEARER)
        cookie = next(c for c in headers.getall("Set-Cookie")
                      if c.startswith("comfyui_auth=")).split(";")[0]
        await self.call_at(base, "GET", "/", headers=basic("wrong"))
        status, _, _ = await self.call_at(base, "GET", "/", headers=BEARER)
        self.assertEqual(status, 429)
        status, _, _ = await self.call_at(base, "GET", "/queue", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

    async def test_requests_without_a_password_do_not_count(self):
        """A browser's first visit, before it shows the prompt, is not a guess."""
        base = await self.throttled_proxy(burst=1)
        for _ in range(5):
            status, _, _ = await self.call_at(base, "GET", "/")
            self.assertEqual(status, 401)
        status, _, _ = await self.call_at(base, "GET", "/", headers=BEARER)
        self.assertEqual(status, 200)

    # -- another site cannot use a signed-in browser ---------------------------

    async def test_cross_site_requests_are_refused_even_signed_in(self):
        for site in ("cross-site", "same-site"):
            for method, mode in (("POST", "cors"), ("POST", "no-cors"),
                                 ("GET", "cors"), ("POST", "navigate"),
                                 ("GET", "websocket")):
                with self.subTest(site=site, method=method, mode=mode):
                    status, _, _ = await self.call(method, "/prompt", headers={
                        **BEARER, "Sec-Fetch-Site": site, "Sec-Fetch-Mode": mode})
                    self.assertEqual(status, 403)
        self.assertEqual(self.seen, [])

    async def test_cross_site_page_load_opens_the_ui(self):
        """A link from the Runpod console is a cross-site page load. ComfyUI
        itself would 403 it, so the proxy must not pass the header on."""
        status, _, _ = await self.call("GET", "/", headers={
            **BEARER, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(status, 200)
        self.assertNotIn("Sec-Fetch-Site", self.seen[0]["headers"])

    async def test_same_origin_requests_pass(self):
        status, _, _ = await self.call("POST", "/prompt", json={}, headers={
            **BEARER, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"})
        self.assertEqual(status, 200)
        self.assertEqual(self.seen[0]["headers"]["Sec-Fetch-Site"], "same-origin")


@unittest.skipIf(aiohttp is None, "aiohttp is not installed")
class FailureBudgetTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("comfyui_auth_proxy", PROXY)
        self.proxy = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"COMFYUI_PASSWORD": PASSWORD}, clear=True):
            spec.loader.exec_module(self.proxy)
        self.now = 0.0

    def budget(self, burst, per_second=1.0):
        return self.proxy.FailureBudget(burst, per_second, clock=lambda: self.now)

    def test_burst_then_steady_rate(self):
        budget = self.budget(burst=2)
        for _ in range(2):
            self.assertFalse(budget.exhausted())
            budget.spend()
        self.assertTrue(budget.exhausted())
        self.now += 0.5
        self.assertTrue(budget.exhausted())
        self.now += 0.5
        self.assertFalse(budget.exhausted())

    def test_logs_once_per_episode_without_details(self):
        budget = self.budget(burst=1)
        budget.spend()
        with mock.patch("builtins.print") as printed:
            budget.exhausted()
            budget.exhausted()
        self.assertEqual(printed.call_count, 1)
        self.assertIn("too many wrong passwords", printed.call_args[0][0])
        self.now += 10
        self.assertFalse(budget.exhausted())
        self.assertFalse(budget.throttling)

    def test_retry_after_counts_the_wait(self):
        budget = self.budget(burst=1, per_second=0.5)
        budget.spend()
        self.assertEqual(budget.retry_after(), 2)


@unittest.skipIf(aiohttp is None, "aiohttp is not installed")
class StartupTest(unittest.TestCase):
    def test_refuses_to_start_without_a_password(self):
        result = subprocess.run(
            [sys.executable, "-I", str(PROXY)],
            env={"PATH": os.environ["PATH"], "COMFYUI_PROXY_PORT": "0"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("COMFYUI_PASSWORD is empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
