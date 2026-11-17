"""Require VLLM_API_KEY on every vLLM route except PUBLIC_PATHS.

vLLM's own --api-key only guards /v1, /v2, /inference and /cohere. This is an
allowlist instead, so routes added upstream are guarded by default. Loaded via
`vllm serve --middleware`, which passes no arguments, hence the env read.
"""

import hashlib
import hmac
import json
import os

# Exact matches only.
PUBLIC_PATHS = frozenset({"/health", "/ping", "/metrics"})

KEY_ENV = "VLLM_API_KEY"

_UNAUTHORIZED = json.dumps({"error": "Unauthorized"}).encode()


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class BearerAuth:
    def __init__(self, app):
        self.app = app
        key = os.environ.get(KEY_ENV, "")
        if not key:
            raise RuntimeError(
                f"runpod_vllm_auth loaded but {KEY_ENV} is empty; refusing to "
                "start vLLM without authentication"
            )
        self._key_digest = _digest(key)

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

        # CORS preflight carries no credentials; vLLM's own check skips it too.
        if kind == "http" and scope.get("method") == "OPTIONS":
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
