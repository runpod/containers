"""Every route of vLLM's real app refuses a request without the key.

Run inside the runpod/vllm-openai image (vllm.yml, "Verify vllm"). Builds the
app `vllm serve` builds, through vLLM's own build_app and --middleware hook,
then calls every route it registered without a key. No GPU or model needed:
the middleware answers before any handler runs.

Fails when upstream adds a route or a middleware that answers ahead of ours,
which a grep of register.py cannot see. Only the parser's frontend args are
parsed: the engine args infer a device, which needs a GPU.
"""

import os
import re
import sys

KEY = "ci-sweep-key"
PUBLIC = {"/health", "/ping", "/metrics"}
MIDDLEWARE = "runpod_vllm_auth.BearerAuth"

os.environ["VLLM_API_KEY"] = KEY
# Registers the dev and RL routers too, so they are swept as well.
os.environ["VLLM_SERVER_DEV_MODE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from starlette.routing import Mount, WebSocketRoute  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
from vllm.entrypoints.common.cli_args import FrontendArgs  # noqa: E402
from vllm.entrypoints.launchers.app import build_app  # noqa: E402
from vllm.tasks import GENERATION_TASKS  # noqa: E402
from vllm.utils.argparse_utils import FlexibleArgumentParser  # noqa: E402


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "x", path)


def ours(response) -> bool:
    # vLLM's own AuthenticationMiddleware answers 401 without this header, so
    # it tells the two apart: ours must be the one answering.
    return (
        response.status_code == 401
        and response.headers.get("www-authenticate") == "Bearer"
    )


def no_key_fails_closed(args) -> list[str]:
    """Loaded without a key and not through start.sh, it must not serve."""
    del os.environ["VLLM_API_KEY"]
    os.environ.pop("RUNPOD_VLLM_UNPROTECTED", None)
    try:
        TestClient(build_app(args, supported_tasks=GENERATION_TASKS)).get("/v1/models")
    except RuntimeError as exc:
        if "VLLM_API_KEY" in str(exc):
            return []
        return [f"no key outside start.sh: unexpected {exc!r}"]
    return ["no key outside start.sh: vLLM's app served a request"]


def main() -> int:
    parser = FrontendArgs.add_cli_args(FlexibleArgumentParser())
    args = parser.parse_args(["--middleware", MIDDLEWARE])
    args.enable_fault_tolerance = True
    app = build_app(args, supported_tasks=GENERATION_TASKS)
    client = TestClient(app, raise_server_exceptions=False)

    failures, checked = [], 0
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        url = concrete(path)
        if isinstance(route, WebSocketRoute):
            checked += 1
            try:
                with client.websocket_connect(url):
                    failures.append(f"WS   {path}: accepted without a key")
            except WebSocketDisconnect as exc:
                # An HTTP denial from another layer subclasses this, no code.
                code = getattr(exc, "code", None)
                if code != 1008:
                    failures.append(f"WS   {path}: {type(exc).__name__} {code}, not 1008")
            continue
        methods = sorted(getattr(route, "methods", None) or {"GET"})
        if isinstance(route, Mount):
            methods = ["GET"]
        for method in methods:
            if method == "HEAD":
                continue
            checked += 1
            response = client.request(method, url)
            if path in PUBLIC:
                if response.status_code == 401:
                    failures.append(f"{method:4} {path}: probe needs a key")
            elif not ours(response):
                failures.append(
                    f"{method:4} {path}: HTTP {response.status_code} without a key"
                )

    # A bare OPTIONS is not a CORS preflight and must not skip the key.
    for path in ("/invocations", "/v1/chat/completions"):
        checked += 1
        if not ours(client.options(path)):
            failures.append(f"OPTIONS {path}: not refused without a key")

    keyed = client.post("/tokenize", headers={"Authorization": f"Bearer {KEY}"})
    if keyed.status_code == 401:
        failures.append("POST /tokenize: 401 even with the right key")

    failures += no_key_fails_closed(args)

    print(f"swept {checked} route/method pairs of vLLM's app")
    for line in failures:
        print(f"::error::{line}")
    return 1 if failures or checked < 20 else 0


if __name__ == "__main__":
    sys.exit(main())
