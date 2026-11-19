#!/usr/bin/env python3
"""Password-checking reverse proxy in front of ComfyUI.

ComfyUI has no authentication and no hook for adding it: the middleware list
is built at server startup and a custom node cannot reach it. So ComfyUI
listens on loopback only and this process owns the public port, checking
the configured password on every request, websocket included, before forwarding it.
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
  COMFYUI_PASSWORD     optional legacy password; takes precedence over a saved hash
  COMFYUI_AUTH_FILE    persistent password hash path (default /workspace/runpod-slim/.comfyui-auth)
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
import hashlib
import html
import math
import os
import secrets
import sys
import tempfile
import time
import urllib.parse

import aiohttp
from aiohttp import web
from yarl import URL

PASSWORD = os.environ.get("COMFYUI_PASSWORD", "")
AUTH_FILE = os.environ.get("COMFYUI_AUTH_FILE", "/workspace/runpod-slim/.comfyui-auth")
MIN_PASSWORD_LENGTH = 12
SETUP_LOG_PREFIX = "ComfyUI first-run setup code:"
SCRYPT_N = 1 << 15
SCRYPT_MAXMEM = 64 * 1024 * 1024


def read_password_hash():
    if not os.path.exists(AUTH_FILE):
        return None
    with open(AUTH_FILE, encoding="ascii") as f:
        value = f.read().strip()
    parts = value.split("$")
    if len(parts) != 3 or parts[0] != "scrypt" or len(parts[1]) != 32 or len(parts[2]) != 128:
        raise ValueError("Invalid ComfyUI authentication file")
    bytes.fromhex(parts[1]); bytes.fromhex(parts[2])
    return value


SAVED_HASH = None if PASSWORD else read_password_hash()
SETUP_CODE = secrets.token_urlsafe(24) if not PASSWORD and not SAVED_HASH else None


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1, maxmem=SCRYPT_MAXMEM)
    return f"scrypt${salt.hex()}${digest.hex()}"


def save_password_hash(value):
    directory = os.path.dirname(AUTH_FILE)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".comfyui-auth-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(value + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.link(temp_path, AUTH_FILE)
    finally:
        os.unlink(temp_path)
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
    """Constant-time comparison. Compared as bytes because compare_digest
    raises TypeError on two str with non-ASCII characters: as str, a
    non-ASCII password or attempt would be a 500 on every request."""
    if not candidate:
        return False
    if PASSWORD:
        return hmac.compare_digest(candidate.encode(), PASSWORD.encode())
    if not SAVED_HASH:
        return False
    _, salt, digest = SAVED_HASH.split("$")
    actual = hashlib.scrypt(candidate.encode(), salt=bytes.fromhex(salt), n=SCRYPT_N, r=8, p=1, maxmem=SCRYPT_MAXMEM)
    return hmac.compare_digest(actual, bytes.fromhex(digest))


def setup_page(error=""):
    message = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Set up ComfyUI | Runpod</title>
<style>
:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #050505; color: #f7f7f8; }
.layout { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.main { display: flex; align-items: center; justify-content: center; padding: 48px 32px; }
.content { width: min(100%, 420px); }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 48px; color: #fff; font-weight: 700; font-size: 18px; letter-spacing: -.03em; }
.brand svg { width: 38px; height: 38px; }
.eyebrow { color: #9b82ff; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; margin: 0 0 12px; }
h1 { font-size: clamp(29px, 3vw, 38px); line-height: 1.12; letter-spacing: -.04em; margin: 0 0 14px; font-weight: 600; }
.intro { color: #a4a3ab; line-height: 1.55; margin: 0 0 30px; font-size: 15px; }
.error { background: #351b24; border: 1px solid #8b344d; border-radius: 8px; color: #ffb5c3; padding: 12px 14px; margin: 0 0 20px; }
label { display: block; font-size: 13px; font-weight: 500; margin: 0 0 17px; }
input { display: block; width: 100%; height: 46px; margin-top: 8px; padding: 0 14px; border: 1px solid #34343a; border-radius: 6px; background: #09090b; color: #fff; font: inherit; outline: none; }
input::placeholder { color: #696971; }
input:focus { border-color: #8064ef; box-shadow: 0 0 0 2px #8064ef55; }
button { width: 100%; height: 46px; margin-top: 9px; border: 0; border-radius: 6px; background: #4c28b3; color: white; font: inherit; font-weight: 600; cursor: pointer; }
button:hover { background: #6239d6; }
button:focus-visible { outline: 2px solid #ae9aff; outline-offset: 3px; }
.note { color: #8e8d97; font-size: 12px; line-height: 1.5; margin-top: 22px; }
.side { position: relative; display: flex; flex-direction: column; justify-content: center; overflow: hidden; padding: clamp(36px, 7vw, 110px); background: radial-gradient(circle at 78% 18%, #43208d 0, transparent 35%), linear-gradient(145deg, #171125, #130e1f 52%, #08070d); border-left: 1px solid #292334; }
.side::before { content: ""; position: absolute; inset: 0; opacity: .28; background-image: linear-gradient(#9b82ff18 1px, transparent 1px), linear-gradient(90deg, #9b82ff18 1px, transparent 1px); background-size: 42px 42px; mask-image: linear-gradient(to bottom, transparent, black 22%, black 80%, transparent); }
.side-inner { position: relative; max-width: 500px; }
.side-mark { display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 64px; margin-bottom: 34px; border: 1px solid #a58cff77; border-radius: 18px; background: #9b82ff24; color: #c5b6ff; font-size: 32px; }
.side h2 { margin: 0 0 18px; font-size: clamp(32px, 4vw, 52px); line-height: 1.08; letter-spacing: -.045em; font-weight: 600; }
.side p { color: #bcb5ca; line-height: 1.6; font-size: 16px; max-width: 400px; }
.steps { display: flex; gap: 9px; margin-top: 38px; }
.steps span { height: 4px; width: 44px; border-radius: 4px; background: #a889ff; }
.steps span + span { background: #77679855; }
@media (max-width: 760px) { .layout { display: block; } .main { min-height: 100vh; padding: 34px 22px; } .brand { margin-bottom: 38px; } .side { display: none; } }
</style></head><body><div class="layout"><main class="main"><div class="content">
<div class="brand"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M20 3 35 11.5v17L20 37 5 28.5v-17L20 3Z M5 11.5 20 20l15-8.5M20 20v17M12 7l15 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg><span>runpod</span></div>
<p class="eyebrow">ComfyUI · First-time setup</p><h1>Secure your workspace</h1>
<p class="intro">In your pod logs, look for a line starting <strong>ComfyUI first-run setup code:</strong> Enter that code, then create a password to access ComfyUI. If the line is gone, restart the pod to generate a new code.</p>
__ERROR__
<form method="post" action="/__runpod/setup"><label for="code">Setup code<input id="code" name="code" required autocomplete="one-time-code" placeholder="Code from your pod logs"></label>
<label for="password">New password<input id="password" type="password" name="password" minlength="12" required autocomplete="new-password" placeholder="At least 12 characters"></label>
<label for="confirm">Confirm password<input id="confirm" type="password" name="confirm" minlength="12" required autocomplete="new-password" placeholder="Enter your password again"></label>
<button type="submit">Set password and continue</button></form>
<p class="note">Your password is stored as a hash on this pod's volume. Keep the setup code private.</p>
</div></main><aside class="side"><div class="side-inner"><div class="side-mark" aria-hidden="true">✦</div><h2>Your workspace,<br>your access.</h2><p>One password protects the ComfyUI interface and its API. With a network volume, your setup follows you to the next pod.</p><div class="steps" aria-hidden="true"><span></span><span></span><span></span></div></div></aside></div></body></html>'''.replace("__ERROR__", message)
    return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"})


async def handle_setup(request):
    global SAVED_HASH, SETUP_CODE
    if request.method == "GET":
        return setup_page()
    if request.method != "POST" or request.headers.get("Sec-Fetch-Site") != "same-origin":
        return web.Response(status=403)
    budget = request.app[BUDGET]
    if budget.exhausted():
        return web.Response(status=429, headers={"Retry-After": str(budget.retry_after())})
    form = await request.post()
    code = str(form.get("code", ""))
    if not hmac.compare_digest(code.encode(), SETUP_CODE.encode()):
        budget.spend()
        return setup_page("Incorrect setup code")
    password = str(form.get("password", ""))
    if len(password) < MIN_PASSWORD_LENGTH or password != form.get("confirm"):
        return setup_page("Passwords must match and be at least 12 characters")
    value = hash_password(password)
    try:
        save_password_hash(value)
    except FileExistsError:
        return web.Response(status=409, text="Already configured. Restart the pod.")
    SAVED_HASH = value
    SETUP_CODE = None
    response = web.Response(status=303, headers={"Location": "/"})
    response.headers["Set-Cookie"] = SESSION_COOKIE
    return response


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


def foreign_origin(request):
    """True when a websocket upgrade's Origin names a host other than the one
    it was sent to. A second check beside Sec-Fetch-Site, for a client that
    omits the Fetch Metadata headers.

    The public hostname is X-Forwarded-Host: behind Runpod's proxy, Host is
    the node's internal address (100.65.x.x:port), so comparing Origin with
    Host refuses every browser's socket. The proxy sets X-Forwarded-Host, and
    a client able to forge it is not a browser, so it has no Origin to
    protect. Host is the fallback for a request that reaches the pod without
    that proxy. Ports are ignored, since the proxy may add or drop them."""
    origin = request.headers.get("Origin")
    if not origin:
        return False
    forwarded = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    host = forwarded or request.headers.get("Host", "")
    split = urllib.parse.urlsplit
    return (split(origin).hostname or "") != (split("//" + host).hostname or "")


async def proxy(request):
    if SETUP_CODE is not None:
        if request.path == "/__runpod/setup":
            return await handle_setup(request)
        if request.method in ("GET", "HEAD"):
            return web.Response(status=303, headers={"Location": "/__runpod/setup"})
        return web.Response(status=403, text="Complete ComfyUI setup first.\n")
    site = request.headers.get("Sec-Fetch-Site")
    navigation = is_navigation(request)
    if site in ("cross-site", "same-site") and not navigation:
        return web.Response(status=403, text="Cross-site request refused.\n")
    websocket = request.headers.get("Upgrade", "").lower() == "websocket"
    if websocket and foreign_origin(request):
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

    if websocket:
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
    if SETUP_CODE is not None:
        print(SETUP_LOG_PREFIX + " " + SETUP_CODE, flush=True)
    print(f"comfyui-auth-proxy: listening on 0.0.0.0:{LISTEN_PORT}, "
          f"forwarding to {UPSTREAM}", flush=True)
    web.run_app(make_app(), host="0.0.0.0", port=LISTEN_PORT,
                access_log=None, print=None)


if __name__ == "__main__":
    main()
