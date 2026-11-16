#!/usr/bin/env python3
"""Password-checking reverse proxy in front of ComfyUI.

ComfyUI has no authentication and no hook for adding it: the middleware list
is built at server startup and a custom node cannot reach it. So ComfyUI
listens on loopback only and this process owns the public port, checking
COMFYUI_PASSWORD on every request, websocket included, before forwarding it.
Being a separate process, it survives ComfyUI and ComfyUI-Manager upgrades.

A request is let through when any one of these carries the password:
  - HTTP Basic auth, any username. This is what a browser prompts for.
  - `Authorization: Bearer <password>`, for API clients.
  - `?token=<password>` on the URL, so a link can sign a browser in. On a GET
    page load the proxy answers with a redirect to the same URL without it.
  - the session cookie this proxy sets after one of the above. Its value is
    random per proxy process and never holds the password, so a pod restart
    ends every session; a browser that cached Basic credentials just resends
    them.

Wrong passwords are rate-limited across all clients: after a burst of them,
requests that carry a password get 429 without it being checked, until the
rate drops. A browser already signed in by its cookie is not affected. The
limit is global because every request reaches the proxy through Runpod's
proxy, so it cannot tell clients apart.

The password is removed from what ComfyUI sees (its Authorization header,
the token parameter and the session cookie) and is never logged: the access
log is off.

Requests whose Sec-Fetch-Site says they come from another site are refused
unless they are a top-level page load. Credentials a browser sends on its own
(Basic auth, the cookie) would otherwise let any web page drive the pod
through the visitor's browser. Page loads stay allowed, so a link from the
Runpod console opens the UI. ComfyUI makes the same check itself, but it is
off whenever --enable-cors-header is passed, and it would refuse that link
too.

Env:
  COMFYUI_PASSWORD     required; the proxy refuses to start without it
  COMFYUI_PROXY_PORT   public port to listen on (default 8188)
  COMFYUI_UPSTREAM     host:port ComfyUI listens on (default 127.0.0.1:18188)

Uses only aiohttp, which ComfyUI itself depends on, so nothing is added to
the image. Run it with the image's interpreter, not the venv on the volume,
so a package installed there cannot change it.
"""

import asyncio
import base64
import binascii
import hmac
import math
import os
import secrets
import sys
import time
import urllib.parse

import aiohttp
from aiohttp import web
from yarl import URL

PASSWORD = os.environ.get("COMFYUI_PASSWORD", "")
LISTEN_PORT = int(os.environ.get("COMFYUI_PROXY_PORT", "8188"))
UPSTREAM = os.environ.get("COMFYUI_UPSTREAM", "127.0.0.1:18188")

COOKIE = "comfyui_auth"
SESSION = secrets.token_urlsafe(32)
CLIENT = web.AppKey("client", aiohttp.ClientSession)

# Wrong passwords allowed back to back, then this many per second.
FAILURE_BURST = 10
FAILURES_PER_SECOND = 1.0
SESSION_COOKIE = f"{COOKIE}={SESSION}; Path=/; HttpOnly; Secure; SameSite=Lax"
CLEAR_COOKIE = f"{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"

# Hop-by-hop headers, plus the ones the client library sets on its own.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
}
WS_HANDSHAKE = {
    "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions",
    "sec-websocket-accept", "sec-websocket-protocol",
}

UNAUTHORIZED_BODY = (
    "ComfyUI on this pod requires a password: the value of the pod's "
    "COMFYUI_PASSWORD environment variable.\n"
    "In a browser, enter it in the sign-in prompt (any username). "
    "From an API client, send it as a Bearer token or HTTP Basic password.\n"
)


class FailureBudget:
    """A leaky bucket of wrong passwords: it holds `burst` and drains at
    `per_second`. While it is full, no password is checked at all, so a
    guesser learns nothing faster than the drain rate."""

    def __init__(self, burst=FAILURE_BURST, per_second=FAILURES_PER_SECOND,
                 clock=time.monotonic):
        self.burst = burst
        self.per_second = per_second
        self.clock = clock
        self.level = 0.0
        self.updated = clock()
        self.throttling = False

    def _drain(self):
        now = self.clock()
        self.level = max(0.0, self.level - (now - self.updated) * self.per_second)
        self.updated = now
        if self.level <= 0.0:
            self.throttling = False

    def exhausted(self):
        self._drain()
        full = self.level + 1 > self.burst
        if full and not self.throttling:
            self.throttling = True
            print("comfyui-auth-proxy: too many wrong passwords; refusing "
                  "password checks (HTTP 429) until they slow down.", flush=True)
        return full

    def spend(self):
        self._drain()
        self.level += 1

    def retry_after(self):
        """Whole seconds until one more attempt fits."""
        return max(1, math.ceil((self.level + 1 - self.burst) / self.per_second))


BUDGET = web.AppKey("budget", FailureBudget)


def matches(candidate):
    """Constant-time comparison, as bytes so non-ASCII input is a mismatch."""
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), PASSWORD.encode())


def session_ok(cookie):
    if not cookie:
        return False
    return hmac.compare_digest(cookie.encode(), SESSION.encode())


def header_credential(header):
    """The password carried by an Authorization header, or None."""
    scheme, _, value = (header or "").partition(" ")
    scheme = scheme.lower()
    value = value.strip()
    if scheme == "bearer":
        return value
    if scheme == "basic":
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        _, sep, password = decoded.partition(":")
        return password if sep else None
    return None


def is_navigation(request):
    return (
        request.method in ("GET", "HEAD")
        and request.headers.get("Sec-Fetch-Mode") == "navigate"
    )


def strip_cookie(header):
    """The Cookie header without this proxy's session cookie."""
    kept = [
        part.strip()
        for part in (header or "").split(";")
        if part.strip() and part.strip().partition("=")[0] != COOKIE
    ]
    return "; ".join(kept)


def upstream_url(request, scheme="http"):
    """Target URL, with the token parameter dropped so ComfyUI never sees it."""
    if "token" not in request.query:
        return URL(f"{scheme}://{UPSTREAM}{request.raw_path}", encoded=True)
    query = [(k, v) for k, v in request.query.items() if k != "token"]
    path = request.raw_path.partition("?")[0]
    target = f"{scheme}://{UPSTREAM}{path}"
    if query:
        target += "?" + urllib.parse.urlencode(query)
    return URL(target, encoded=True)


def forward_headers(request, drop_authorization, drop_fetch_site):
    headers = []
    for name, value in request.headers.items():
        lower = name.lower()
        if lower in HOP_BY_HOP or lower in WS_HANDSHAKE:
            continue
        if lower == "authorization" and drop_authorization:
            continue
        if lower == "sec-fetch-site" and drop_fetch_site:
            continue
        if lower == "cookie":
            value = strip_cookie(value)
            if not value:
                continue
        headers.append((name, value))
    return headers


def credentials(request):
    """Where the request carries the password: a set of "cookie", "header"
    and "token", plus a 429 response to send instead when wrong passwords
    have used up the budget. Only requests that are not signed in by the
    cookie draw on the budget; a signed-in one cannot be guessing."""
    found = set()
    header_value = header_credential(request.headers.get("Authorization"))
    token_value = request.query.get("token")
    signed_in = session_ok(request.cookies.get(COOKIE))
    if signed_in:
        found.add("cookie")
    elif header_value or token_value:
        budget = request.app[BUDGET]
        if budget.exhausted():
            return found, web.Response(
                status=429,
                text="Too many wrong passwords for this pod; try again shortly.\n",
                headers={"Retry-After": str(budget.retry_after())},
            )
    if matches(header_value):
        found.add("header")
    if matches(token_value):
        found.add("token")
    if not found and (header_value or token_value):
        request.app[BUDGET].spend()
    return found, None


def unauthorized(request):
    response = web.Response(
        status=401,
        text=UNAUTHORIZED_BODY,
        headers={"WWW-Authenticate": 'Basic realm="ComfyUI", charset="UTF-8"'},
    )
    if COOKIE in request.cookies:
        response.headers["Set-Cookie"] = CLEAR_COOKIE
    return response


def sign_in_redirect(request):
    """A ?token= page load: redirect to the same URL without the token, so the
    password leaves the address bar. Leading slashes and backslashes are
    collapsed, or `//evil.example/?token=...` would send the browser to
    another site."""
    target = str(upstream_url(request).relative())
    location = "/" + target.lstrip("/\\")
    response = web.Response(status=302, headers={"Location": location})
    response.headers["Set-Cookie"] = SESSION_COOKIE
    return response


async def proxy(request):
    site = request.headers.get("Sec-Fetch-Site")
    navigation = is_navigation(request)
    if site in ("cross-site", "same-site") and not navigation:
        return web.Response(status=403, text="Cross-site request refused.\n")

    found, refusal = credentials(request)
    if refusal is not None:
        return refusal
    if not found:
        return unauthorized(request)

    if "token" in found and navigation:
        return sign_in_redirect(request)
    headers = forward_headers(
        request,
        drop_authorization="header" in found,
        # ComfyUI refuses every cross-site request, page loads included; the
        # check above already decided which ones may pass.
        drop_fetch_site=site == "cross-site",
    )
    session = request.app[CLIENT]

    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request, session, headers)
    return await proxy_http(request, session, headers,
                            set_cookie="cookie" not in found)


async def proxy_http(request, session, headers, set_cookie):
    data = request.content.iter_any() if request.body_exists else None
    try:
        upstream = await session.request(
            request.method,
            upstream_url(request),
            headers=headers,
            data=data,
            allow_redirects=False,
        )
    except aiohttp.ClientError:
        return web.Response(
            status=502,
            text="ComfyUI is not answering yet. It may still be starting; "
            "the pod logs say when it is ready.\n",
        )

    async with upstream:
        response = web.StreamResponse(status=upstream.status, reason=upstream.reason)
        for name, value in upstream.headers.items():
            if name.lower() in HOP_BY_HOP:
                continue
            response.headers.add(name, value)
        if set_cookie:
            response.headers.add("Set-Cookie", SESSION_COOKIE)
        await response.prepare(request)
        if request.method != "HEAD":
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
        await response.write_eof()
        return response


async def proxy_websocket(request, session, headers):
    protocols = [
        p.strip()
        for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if p.strip()
    ]
    try:
        upstream = await session.ws_connect(
            upstream_url(request, "ws"),
            headers=headers,
            protocols=protocols,
            max_msg_size=0,
        )
    except (aiohttp.ClientError, aiohttp.WSServerHandshakeError):
        return web.Response(status=502, text="ComfyUI is not answering yet.\n")

    downstream = web.WebSocketResponse(
        protocols=[upstream.protocol] if upstream.protocol else (),
        max_msg_size=0,
    )
    await downstream.prepare(request)

    async def pump(source, sink):
        async for message in source:
            if message.type == aiohttp.WSMsgType.TEXT:
                await sink.send_str(message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                await sink.send_bytes(message.data)
            else:
                break

    tasks = [
        asyncio.ensure_future(pump(downstream, upstream)),
        asyncio.ensure_future(pump(upstream, downstream)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await upstream.close()
        await downstream.close()
    return downstream


async def open_client(app):
    app[CLIENT] = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=0),
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
    )
    yield
    await app[CLIENT].close()


def make_app(budget=None):
    app = web.Application()
    app[BUDGET] = budget or FailureBudget()
    app.cleanup_ctx.append(open_client)
    app.router.add_route("*", "/{tail:.*}", proxy)
    return app


def main():
    if not PASSWORD:
        print("comfyui-auth-proxy: COMFYUI_PASSWORD is empty; refusing to start.",
              file=sys.stderr)
        sys.exit(2)
    print(f"comfyui-auth-proxy: listening on 0.0.0.0:{LISTEN_PORT}, "
          f"forwarding to {UPSTREAM}", flush=True)
    web.run_app(make_app(), host="0.0.0.0", port=LISTEN_PORT,
                access_log=None, print=None)


if __name__ == "__main__":
    main()
