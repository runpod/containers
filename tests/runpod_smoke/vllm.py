"""runpod/vllm-openai: the auth gate and one completion, over the public proxy.

This is the claim the image exists to make, checked from outside the Pod the
way a user reaches it: probes open, every other route closed without the key
(including the ones vLLM's own --api-key leaves open), and the key opens them.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from . import config

_UA = "runpod-smoke-test/1.0"


def _base_url(pod_id: str) -> str:
    return f"https://{pod_id}-{config.VLLM_PORT}.proxy.runpod.net"


def _request(
    url: str, *, key: Optional[str] = None, body: Optional[dict] = None,
    timeout: int = 30,
) -> tuple[int, bytes]:
    headers = {"User-Agent": _UA}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_for_vllm(
    pod_id: str, on_line: Callable[[str], None],
) -> tuple[bool, str]:
    """Poll /health until vLLM has loaded the model. It binds :8000 only once
    the engine is up, so the proxy answers 502 until then."""
    url = _base_url(pod_id) + "/health"
    deadline = time.monotonic() + config.VLLM_WAIT_TIMEOUT
    last, attempt = "", 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            code, _ = _request(url, timeout=10)
            last = f"HTTP {code}"
        except OSError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if last == "HTTP 200":
            on_line(f"GET /health: HTTP 200 after {attempt} attempts")
            return True, ""
        if attempt % 12 == 1:
            on_line(f"GET /health: {last} (waiting for the model to load)")
        time.sleep(10)
    return False, (
        f"/health not 200 after {config.VLLM_WAIT_TIMEOUT}s, last: {last}"
    )


def check_vllm_auth(
    pod_id: str, on_line: Callable[[str], None],
) -> tuple[bool, str]:
    base = _base_url(pod_id)
    key = config.VLLM_TEST_API_KEY
    probes = [
        # (label, method, path, key, expected status)
        ("probe, no key", "GET", "/health", None, 200),
        ("probe, no key", "GET", "/metrics", None, 200),
        ("no key", "GET", "/v1/models", None, 401),
        ("wrong key", "GET", "/v1/models", "wrong-" + key, 401),
        # Open under vLLM's own --api-key; the reason this image exists.
        ("no key", "POST", "/invocations", None, 401),
        ("no key", "POST", "/tokenize", None, 401),
        ("no key", "GET", "/version", None, 401),
        ("right key", "GET", "/v1/models", key, 200),
    ]
    for label, method, path, auth, expected in probes:
        body = {} if method == "POST" else None
        try:
            code, _ = _request(base + path, key=auth, body=body)
        except OSError as exc:
            return False, f"{method} {path} ({label}): {type(exc).__name__}: {exc}"
        on_line(f"{method} {path} ({label}): HTTP {code}")
        if code != expected:
            return False, f"{method} {path} ({label}): HTTP {code}, expected {expected}"
    return True, ""


def check_vllm_completion(
    pod_id: str, on_line: Callable[[str], None],
) -> tuple[bool, str]:
    body = {
        "model": config.VLLM_TEST_MODEL,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 32,
        "temperature": 0,
    }
    try:
        code, raw = _request(
            _base_url(pod_id) + "/v1/chat/completions",
            key=config.VLLM_TEST_API_KEY, body=body, timeout=120,
        )
    except OSError as exc:
        return False, f"chat completion: {type(exc).__name__}: {exc}"
    if code != 200:
        return False, f"chat completion: HTTP {code} {raw[:160]!r}"
    try:
        message = json.loads(raw)["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        return False, f"chat completion: unexpected body {raw[:160]!r}"
    text = (message.get("content") or message.get("reasoning_content") or "").strip()
    on_line(f"POST /v1/chat/completions: HTTP 200, {text[:60]!r}")
    if not text:
        return False, "chat completion: empty reply"
    return True, ""


def probe_vllm_alive(
    pod_id: str, attempts: int = 3, retry_sleep: int = 5,
) -> tuple[bool, str]:
    """Post-dwell re-probe: still serving, gate still closed.

    A proxy read timeout is retried — CI saw one on a pod that was serving
    fine. A wrong status code is the image's answer and is not."""
    base = _base_url(pod_id)
    for attempt in range(1, attempts + 1):
        try:
            health, _ = _request(base + "/health", timeout=15)
            models, _ = _request(base + "/v1/models", timeout=15)
            break
        except OSError as exc:
            if attempt == attempts:
                return False, (
                    f"{type(exc).__name__}: {exc} ({attempts} attempt(s))"
                )
            time.sleep(retry_sleep)
    detail = f"/health {health}, /v1/models without key {models}"
    return health == 200 and models == 401, detail
