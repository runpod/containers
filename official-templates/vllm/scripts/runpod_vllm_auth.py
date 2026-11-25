"""Require VLLM_API_KEY on every vLLM route except PUBLIC_PATHS.

vLLM's own --api-key only guards /v1, /v2, /inference and /cohere. This is an
allowlist instead, so routes added upstream are guarded by default. Loaded via
`vllm serve --middleware`, which passes no arguments, hence the env read.

Without a key every request passes, and the warning is repeated in the logs
while the server is in use.
"""

import hashlib
import hmac
import json
import os
import sys
import time

# Exact matches only.
PUBLIC_PATHS = frozenset({"/health", "/ping", "/metrics"})

KEY_ENV = "VLLM_API_KEY"

# Repeated on traffic, at most this often, so it stays near the latest logs.
WARN_EVERY_SEC = 600

UNPROTECTED_WARNING = f"""\
############################################################
  WARNING: vLLM is NOT PROTECTED: {KEY_ENV} is not set.

  Anyone with this Pod's URL can use every route on :8000,
  run the model and spend this Pod's GPU time.

  Set the environment variable
    {KEY_ENV}=<a long random secret>
  and restart the Pod. Every request will then need the header
    Authorization: Bearer <{KEY_ENV}>
############################################################"""

_UNAUTHORIZED = json.dumps({"error": "Unauthorized"}).encode()


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _is_preflight(scope) -> bool:
    if scope.get("method") != "OPTIONS":
        return False
    names = {name.lower() for name, _ in scope.get("headers") or ()}
    return b"origin" in names and b"access-control-request-method" in names


class BearerAuth:
    def __init__(self, app):
        self.app = app
        key = os.environ.get(KEY_ENV, "").strip()
        self._key_digest = _digest(key) if key else None
        self._warned_at = None
        if self._key_digest is None:
            self._warn_unprotected()

    def _warn_unprotected(self) -> None:
        self._warned_at = time.monotonic()
        print(UNPROTECTED_WARNING, file=sys.stderr, flush=True)

    def _authorized(self, scope) -> bool:
        for name, value in scope.get("headers") or ():
            if name.lower() != b"authorization":
                continue
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() != "bearer":
                return False
            return hmac.compare_digest(_digest(token), self._key_digest)
        return False

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        if self._key_digest is None:
            if time.monotonic() - self._warned_at >= WARN_EVERY_SEC:
                self._warn_unprotected()
            return await self.app(scope, receive, send)

        # A CORS preflight carries no credentials. Anything else sent as
        # OPTIONS still reaches a route, so it needs the key.
        if kind == "http" and _is_preflight(scope):
            return await self.app(scope, receive, send)

        root_path = scope.get("root_path", "")
        path = scope["path"]
        if root_path and path.startswith(root_path):
            path = path[len(root_path):]

        if path in PUBLIC_PATHS or self._authorized(scope):
            return await self.app(scope, receive, send)

        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED})
