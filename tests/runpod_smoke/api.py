"""RunPod REST API v2 client.

Replaces the `runpodctl` subprocess calls. One place for the API key,
request plumbing and the mapping from HTTP status + `ErrorResponse` onto
the outcome vocabulary the runner speaks.

Every helper returns `(status, data)` instead of raising, matching the
style in comfyui.py: transport failures come back as status 0 so callers
classify them like any other error.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .log import log


BASE_URL = "https://api.runpod.io/v2"

# api.runpod.io sits behind Cloudflare, which rejects the default
# Python-urllib User-Agent with error 1010.
_UA = "test-images.py/1.0 (+runpod-smoketest)"

# Status 0 is our own marker for "the request never got an HTTP reply"
# (DNS, connection reset, socket timeout).
_TRANSPORT_ERROR = 0


def load_api_key() -> Optional[str]:
    """Read the API key from RUNPOD_API_KEY, else ~/.runpod/config.toml.

    The file is regex'd rather than parsed so we don't need tomli — the
    CLI always writes the key on a single line as `apikey = '...'`.
    """
    env = os.environ.get("RUNPOD_API_KEY", "").strip()
    if env:
        return env
    cfg = Path.home() / ".runpod" / "config.toml"
    if not cfg.is_file():
        return None
    try:
        text = cfg.read_text()
    except OSError:
        return None
    m = re.search(r"apikey\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def request(
    method: str,
    path: str,
    *,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 60,
) -> tuple[int, object]:
    """Call the v2 API. Returns `(status, parsed_body)`.

    status 0 means the request never reached the API. `parsed_body` is the
    decoded JSON, or None for 204 / non-JSON / transport failures.
    """
    api_key = load_api_key()
    if not api_key:
        return _TRANSPORT_ERROR, {"detail": "no RunPod API key available"}

    url = f"{BASE_URL}{path}"
    if params:
        # Repeated keys would be wrong here: the v2 API takes multi-valued
        # query params (include, product, cudaVersions) comma-separated.
        flat = {
            k: ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
            for k, v in params.items()
            if v not in (None, "", [], ())
        }
        if flat:
            url += "?" + urllib.parse.urlencode(flat)

    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": _UA,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001 — body is best-effort
            pass
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"detail": raw.decode("utf-8", "replace")[:500]}
    except (OSError, ValueError) as exc:
        # urllib.error.URLError and TimeoutError both derive from OSError.
        return _TRANSPORT_ERROR, {"detail": f"{type(exc).__name__}: {exc}"}


def error_detail(status: int, data: object) -> str:
    """Flatten an ErrorResponse into one line for logs and FAIL notes."""
    if not isinstance(data, dict):
        return f"HTTP {status}"
    parts = [str(data.get("detail") or data.get("title") or "").strip()]
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        parts.append("; ".join(str(e) for e in errors[:3]))
    text = " — ".join(p for p in parts if p)
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# Capacity shortage has no machine-readable code of its own — the v2 docs
# say so explicitly — so it has to be recognised from `detail`. Same
# phrasings the runpodctl-era regex covered, since the wording comes from
# the same orchestrator.
_UNAVAILABLE_RE = re.compile(
    r"no\s+longer\s+any\s+instances\s+available"
    r"|please\s+refresh\s+and\s+try\s+again"
    r"|does\s+not\s+have\s+the\s+resources"
    r"|try\s+a\s+different\s+machine"
    r"|no\s+(?:machines|capacity|hosts|gpus|instances)\s+available"
    r"|insufficient\s+capacity"
    r"|unavailable"
    r"|out\s+of\s+stock"
    r"|sold\s+out"
    r"|no\s+capacity",
    re.IGNORECASE,
)

_TRANSIENT_RE = re.compile(
    r"something\s+went\s+wrong"
    r"|please\s+try\s+again\s+later"
    r"|contact\s+support"
    r"|internal\s+server\s+error"
    r"|timeout|timed\s+out"
    r"|connection\s+(?:reset|refused)",
    re.IGNORECASE,
)

# Retry these regardless of body: 429 is rate limiting, 5xx is the API
# itself, 0 is a transport failure that may not have reached the API.
_TRANSIENT_STATUSES = {_TRANSPORT_ERROR, 429, 500, 502, 503, 504}


def classify_error(status: int, data: object) -> str:
    """Map a failed response to 'UNAVAILABLE', 'TRANSIENT' or 'FATAL'.

    UNAVAILABLE — no capacity for this instance; caller tries the next one.
    TRANSIENT   — worth retrying the same request.
    FATAL       — bad request, auth, missing image; retrying won't help.

    Status is consulted first: rate limiting and 5xx are infrastructure, so
    a 503 is never "this GPU type is full". Capacity is reported as 400 with
    only a human-readable `detail`, so it can only be recognised by wording.

    Only `detail` is matched, never `title` — the title is a generic HTTP
    reason phrase, and "Service Unavailable" would otherwise read as a
    capacity shortage and make us abandon a perfectly good GPU type.
    """
    if status in _TRANSIENT_STATUSES:
        return "TRANSIENT"
    detail = str(data.get("detail") or "") if isinstance(data, dict) else ""
    if detail and _UNAVAILABLE_RE.search(detail):
        return "UNAVAILABLE"
    if detail and _TRANSIENT_RE.search(detail):
        return "TRANSIENT"
    return "FATAL"


def request_with_retries(
    method: str,
    path: str,
    *,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 60,
    attempts: int = 3,
    backoff: int = 3,
) -> tuple[int, object]:
    """`request` plus retries on TRANSIENT. For idempotent reads and for
    deletes; pod creation drives its own retry loop so it can log per
    attempt and count against CREATE_RETRIES."""
    status: int = _TRANSPORT_ERROR
    data: object = None
    for attempt in range(1, attempts + 1):
        status, data = request(
            method, path, body=body, params=params, timeout=timeout
        )
        if 200 <= status < 300:
            return status, data
        if classify_error(status, data) != "TRANSIENT" or attempt == attempts:
            return status, data
        time.sleep(backoff * attempt)
    return status, data


def api_available() -> tuple[bool, str]:
    """Cheap credential check used at startup. Any authenticated 2xx will
    do; the SSH-keys endpoint is the smallest one that needs no arguments."""
    if not load_api_key():
        return False, (
            "no RunPod API key — set RUNPOD_API_KEY or log in so "
            "~/.runpod/config.toml has one"
        )
    status, data = request("GET", "/account/ssh-keys", timeout=20)
    if 200 <= status < 300:
        return True, ""
    if status in (401, 403):
        return False, f"RunPod API rejected the key ({error_detail(status, data)})"
    return False, f"RunPod API unreachable ({error_detail(status, data)})"


def log_error(context: str, status: int, data: object, indent: int = 1) -> None:
    log(f"{context}: {error_detail(status, data)}", indent=indent)
