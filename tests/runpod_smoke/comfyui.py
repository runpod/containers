"""ComfyUI public-proxy smoke and end-to-end generation checks."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import config

_UA = "runpod-smoke-test/1.0"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _base_url(pod_id: str) -> str:
    return config.proxy_url(pod_id, config.COMFYUI_PORT)


def auth_headers() -> dict:
    """Basic auth with the test pod's COMFYUI_PASSWORD, as a browser sends it."""
    token = base64.b64encode(f"smoke:{config.COMFYUI_TEST_PASSWORD}".encode())
    return {"Authorization": "Basic " + token.decode()}


def _request(
    url: str, data: Optional[bytes] = None, timeout: int = 30,
    authenticated: bool = True, browser: bool = True,
) -> tuple[int, bytes]:
    headers = {"User-Agent": _UA}
    if authenticated:
        headers.update(auth_headers())
        if browser:
            headers["Sec-Fetch-Site"] = "same-origin"
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def probe_comfyui_alive(
    pod_id: str, retries: int = 3, retry_sleep: int = 5,
) -> tuple[bool, str]:
    """Quick post-dwell probe; this is not the initial readiness wait."""
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            code, _ = _request(_base_url(pod_id) + "/system_stats", timeout=10)
            if code == 200:
                return True, f"HTTP 200 (attempt #{attempt})"
            last_error = f"HTTP {code}"
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(retry_sleep)
    return False, last_error


def check_comfyui_refuses_anonymous(pod_id: str) -> tuple[bool, str]:
    """Through the public proxy, nothing may reach ComfyUI without the
    password: queueing a workflow, reading the UI, or a wrong password."""
    base = _base_url(pod_id)
    probes = [
        ("POST /prompt, no password", base + "/prompt", b"{}"),
        ("GET /, no password", base + "/", None),
        ("GET /system_stats, no password", base + "/system_stats", None),
    ]
    lines = []
    for label, url, data in probes:
        try:
            code, _ = _request(url, data, timeout=20, authenticated=False)
        except OSError as exc:
            return False, f"{label}: {type(exc).__name__}: {exc}"
        lines.append(f"{label}: HTTP {code}")
        if code != 401:
            return False, "; ".join(lines) + " (expected 401)"
    wrong = urllib.request.Request(
        base + "/system_stats",
        headers={"User-Agent": _UA, "Authorization": "Bearer not-the-password"},
    )
    try:
        with urllib.request.urlopen(wrong, timeout=20) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except OSError as exc:
        return False, f"wrong password: {type(exc).__name__}: {exc}"
    lines.append(f"GET /system_stats, wrong password: HTTP {code}")
    if code != 401:
        return False, "; ".join(lines) + " (expected 401)"
    return True, "; ".join(lines)


def _filebrowser_request(
    url: str, method: str = "GET", headers: Optional[dict] = None,
    timeout: int = 20,
) -> tuple[int, list[str]]:
    """Return the status and the Set-Cookie headers."""
    request = urllib.request.Request(
        url, data=b"" if method == "POST" else None, method=method,
        headers={"User-Agent": _UA, **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_all("Set-Cookie") or []


def check_filebrowser_requires_password(pod_id: str) -> tuple[bool, str]:
    """Through the public proxy, FileBrowser lists /workspace only after admin
    signs in with the pod's FILEBROWSER_PASSWORD."""
    base = f"https://{pod_id}-{config.FILEBROWSER_PORT}.proxy.runpod.net"
    listing = base + "/api/resources?" + urllib.parse.urlencode(
        {"source": "workspace", "path": "/"}
    )
    login = base + "/api/auth/login?username=admin"
    probes = [
        # (label, url, method, headers, expected status)
        ("GET /api/resources, no session", listing, "GET", {}, 401),
        ("login, wrong password", login, "POST",
         {"X-Password": "not-the-password"}, 401),
        ("login, classic default", login, "POST",
         {"X-Password": "adminadmin12"}, 401),
        ("login, FILEBROWSER_PASSWORD", login, "POST",
         {"X-Password": config.FILEBROWSER_TEST_PASSWORD}, 200),
    ]
    lines = []
    cookies: list[str] = []
    for label, url, method, headers, expected in probes:
        try:
            code, cookies = _filebrowser_request(url, method, headers)
        except OSError as exc:
            return False, f"{label}: {type(exc).__name__}: {exc}"
        lines.append(f"{label}: HTTP {code}")
        if code != expected:
            return False, "; ".join(lines) + f" (expected {expected})"
    if not cookies:
        return False, "; ".join(lines) + " (login set no session cookie)"
    session = "; ".join(cookie.split(";", 1)[0] for cookie in cookies)
    try:
        code, _ = _filebrowser_request(listing, headers={"Cookie": session})
    except OSError as exc:
        return False, f"GET /api/resources, session: {type(exc).__name__}: {exc}"
    lines.append(f"GET /api/resources, session: HTTP {code}")
    if code != 200:
        return False, "; ".join(lines) + " (expected 200)"
    return True, "; ".join(lines)


def _wait_for_system_stats(base: str, emit: Callable[[str], None]) -> bool:
    deadline = time.monotonic() + config.COMFYUI_WAIT_TIMEOUT
    attempt = 0
    last_error = ""
    while time.monotonic() < deadline:
        attempt += 1
        try:
            code, _ = _request(base + "/system_stats", timeout=10)
            if code == 200:
                emit(f"ComfyUI /system_stats OK after {attempt} probe(s)")
                return True
            last_error = f"HTTP {code}"
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt % 10 == 0:
            emit(f"  ...waiting for ComfyUI (last={last_error})")
        time.sleep(5)
    emit(f"FAIL: /system_stats unavailable after {config.COMFYUI_WAIT_TIMEOUT}s ({last_error})")
    return False


def _load_json(path: str) -> object:
    with open(path, "rb") as file:
        return json.load(file)


def _wait_for_routes(base: str, emit: Callable[[str], None]) -> bool:
    deadline = time.monotonic() + config.COMFYUI_ROUTES_TIMEOUT
    last_error = ""
    while time.monotonic() < deadline:
        try:
            code, body = _request(base + "/server_download/folder_paths", timeout=20)
            if code == 200:
                json.loads(body)
                return True
            last_error = f"HTTP {code}"
        except (OSError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(3)
    emit(f"FAIL: RunpodDirect routes unavailable ({last_error})")
    return False


# The URL does not exist, so a guard that regresses fails the check without
# writing anything to the pod.
_GUARD_URL = "https://huggingface.co/runpod/smoke-test-missing/resolve/main/none.bin"
# (name, browser, save_path, filename, expected status, marker in the error)
_DOWNLOAD_GUARDS = (
    ("non-browser caller", False, "checkpoints", "smoke.safetensors", 403, b"browser ui"),
    ("save outside models/", True, "custom_nodes", "smoke.safetensors", 400, b"models directory"),
    ("executable filename", True, "checkpoints", "smoke.py", 400, b"executable"),
)


def _check_download_guards(base: str, emit: Callable[[str], None]) -> bool:
    """RunpodDirect refuses downloads the UI would never make."""
    for name, browser, save_path, filename, expected, marker in _DOWNLOAD_GUARDS:
        payload = {"url": _GUARD_URL, "save_path": save_path, "filename": filename}
        try:
            code, body = _request(
                base + "/server_download/start",
                json.dumps(payload).encode(),
                timeout=30, browser=browser,
            )
        except OSError as exc:
            emit(f"FAIL: RunpodDirect guard '{name}' request errored: {exc}")
            return False
        if code != expected or marker not in body.lower():
            emit(
                f"FAIL: RunpodDirect guard '{name}' returned HTTP {code}, "
                f"expected {expected}: {body[:300]!r}"
            )
            return False
        emit(f"OK: RunpodDirect refuses {name} (HTTP {code})")
    return True


def _ensure_model(base: str, model: dict, emit: Callable[[str], None]) -> bool:
    directory = model.get("directory", "checkpoints")
    filename = model["filename"]
    verify = {"directory": directory, "filename": filename}
    if model.get("sha256"):
        verify.update({"hash": model["sha256"], "hash_type": "sha256"})
    try:
        code, body = _request(
            base + "/server_download/verify_model_integrity",
            json.dumps(verify).encode(),
            timeout=180,
        )
        verified = json.loads(body) if code == 200 else {}
    except (OSError, json.JSONDecodeError):
        verified = {}
    if verified.get("exists") and verified.get("valid"):
        emit(f"model already present + verified: {directory}/{filename}")
        return True

    payload = {"url": model["url"], "save_path": directory, "filename": filename}
    if model.get("sha256"):
        payload.update({"hash": model["sha256"], "hash_type": "sha256"})
    try:
        code, body = _request(
            base + "/server_download/start", json.dumps(payload).encode(), timeout=60
        )
    except OSError as exc:
        emit(f"FAIL: model download request errored: {exc}")
        return False
    if code == 400 and b"already exists" in body.lower():
        return True
    if code != 200:
        emit(f"FAIL: model download request returned HTTP {code}: {body[:300]!r}")
        return False

    status_url = (
        f"{base}/server_download/status/{directory}/"
        f"{urllib.parse.quote(filename)}"
    )
    deadline = time.monotonic() + config.COMFYUI_DOWNLOAD_TIMEOUT
    while time.monotonic() < deadline:
        try:
            code, body = _request(status_url, timeout=20)
            status = json.loads(body) if code == 200 else {}
        except (OSError, json.JSONDecodeError):
            status = {}
        if status.get("status") == "completed":
            emit(f"download complete: {directory}/{filename}")
            return True
        if status.get("status") in {"error", "cancelled"}:
            emit(f"FAIL: download {status['status']}: {status.get('error', '')}")
            return False
        time.sleep(3)
    emit(f"FAIL: model download timed out after {config.COMFYUI_DOWNLOAD_TIMEOUT}s")
    return False


def _wait_for_image(
    base: str, prompt_id: str, emit: Callable[[str], None],
) -> Optional[dict]:
    deadline = time.monotonic() + config.COMFYUI_GEN_TIMEOUT
    while time.monotonic() < deadline:
        try:
            code, body = _request(base + f"/history/{prompt_id}", timeout=20)
            history = json.loads(body).get(prompt_id) if code == 200 else None
        except (OSError, json.JSONDecodeError):
            history = None
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                emit(f"FAIL: execution error: {json.dumps(status)[:1000]}")
                return None
            for output in history.get("outputs", {}).values():
                images = output.get("images") or []
                if images:
                    return images[0]
            if status.get("completed") is True:
                emit("FAIL: prompt completed but produced no image outputs")
                return None
        time.sleep(3)
    emit(f"FAIL: generation did not finish in {config.COMFYUI_GEN_TIMEOUT}s")
    return None


def _wait_for_checkpoints(base: str, workflow: dict) -> bool:
    """Wait briefly for ComfyUI to index models downloaded after startup."""
    names = {
        node.get("inputs", {}).get("ckpt_name")
        for node in workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") == "CheckpointLoaderSimple"
    }
    names.discard(None)
    if not names:
        return True
    for _ in range(15):
        try:
            code, body = _request(
                base + "/object_info/CheckpointLoaderSimple", timeout=30
            )
            choices = json.loads(body)[
                "CheckpointLoaderSimple"
            ]["input"]["required"]["ckpt_name"][0]
            if names.issubset(choices):
                return True
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
        time.sleep(2)
    return False


def _validate_image(
    base: str, image: dict, save_dir: str, tag: str, emit: Callable[[str], None],
) -> bool:
    query = urllib.parse.urlencode(
        {
            "filename": image.get("filename", ""),
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    try:
        code, data = _request(base + "/view?" + query, timeout=60)
    except OSError as exc:
        emit(f"FAIL: image fetch errored: {exc}")
        return False
    if code != 200 or len(data) < 1000 or data[:8] != _PNG_MAGIC:
        emit(f"FAIL: invalid PNG response (HTTP {code}, {len(data)} bytes)")
        return False
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if not (width > 0 and height > 0):
        emit(f"FAIL: PNG has invalid IHDR dimensions ({width}x{height})")
        return False
    if save_dir:
        try:
            os.makedirs(save_dir, exist_ok=True)
            filename = os.path.basename(image.get("filename", "output.png"))
            with open(os.path.join(save_dir, f"{tag}_{filename}"), "wb") as file:
                file.write(data)
        except OSError as exc:
            emit(f"warn: could not save output PNG: {exc}")
    emit(f"OK: validated PNG ({len(data)} bytes, {width}x{height})")
    return True


def run_comfyui_check(
    pod_id: str,
    on_line: Optional[Callable[[str], None]] = None,
    save_dir: str = "",
    tag: str = "",
) -> tuple[bool, str]:
    """Provision a model, generate an image, and validate the resulting PNG."""
    emit = on_line or (lambda _message: None)
    base = _base_url(pod_id)
    emit(f"ComfyUI functional check via proxy: {base}")
    if not _wait_for_system_stats(base, emit):
        return False, "ComfyUI /system_stats unavailable"
    try:
        workflow = _load_json(config.COMFYUI_WORKFLOW)
        models = _load_json(config.COMFYUI_MODELS_MANIFEST)
    except OSError as exc:
        return False, f"could not read test assets: {exc}"
    if not _wait_for_routes(base, emit):
        return False, "ComfyUI-RunpodDirect routes unavailable"
    if not _check_download_guards(base, emit):
        return False, "ComfyUI-RunpodDirect accepted a download it must refuse"
    for model in models:
        if not _ensure_model(base, model, emit):
            return False, f"model provisioning failed: {model.get('filename')}"
    if not _wait_for_checkpoints(base, workflow):
        return False, "ComfyUI did not index the downloaded checkpoint"
    code, body = _request(
        base + "/prompt",
        json.dumps({"prompt": workflow, "client_id": "runpod-smoke"}).encode(),
        timeout=60,
    )
    body_text = body.decode("utf-8", "replace")
    if code != 200:
        emit(f"FAIL: POST /prompt returned HTTP {code}: {body_text[:1000]}")
        return False, f"workflow rejected by /prompt (HTTP {code})"
    try:
        response = json.loads(body)
    except json.JSONDecodeError:
        emit(f"FAIL: /prompt returned non-JSON: {body_text[:300]}")
        return False, "workflow returned invalid JSON"
    node_errors = response.get("node_errors") or {}
    if node_errors:
        emit(f"FAIL: /prompt reported node_errors: {json.dumps(node_errors)[:1000]}")
        return False, "workflow rejected with node errors"
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        return False, "workflow response did not include prompt_id"
    image = _wait_for_image(base, prompt_id, emit)
    if not image:
        return False, "generation produced no image or errored"
    if not _validate_image(base, image, save_dir, tag, emit):
        return False, "output PNG failed validation"
    emit("COMFYUI FUNCTIONAL CHECK OK")
    return True, "generated + validated PNG"


# ---------------------------------------------------------------------------
# ComfyUI-Manager install check
# ---------------------------------------------------------------------------

# A fixed client_id so queue/status and queue/history can be filtered to our
# own install task instead of whatever else the pod is doing.
_MANAGER_CLIENT_ID = "runpod-smoke-manager"

# Prefix on a detail string that means "the pod or the registry stopped
# answering", so the runner can report UNVERIFIED instead of blaming the image.
MANAGER_UNVERIFIED = "manager check UNVERIFIED"


def _wait_for_manager(base: str, emit: Callable[[str], None]) -> bool:
    """Wait for ComfyUI-Manager's HTTP API to answer (it loads after ComfyUI)."""
    deadline = time.monotonic() + config.COMFYUI_MANAGER_READY_TIMEOUT
    last_error = ""
    while time.monotonic() < deadline:
        try:
            code, body = _request(base + "/v2/manager/version", timeout=10)
            if code == 200:
                emit(f"ComfyUI-Manager ready (v{body.decode('utf-8', 'replace').strip()})")
                return True
            last_error = f"HTTP {code}"
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(3)
    emit(f"FAIL: ComfyUI-Manager /v2/manager/version unavailable ({last_error})")
    return False


def _object_info_has_class(base: str, node_class: str) -> bool:
    """True when ComfyUI reports the node class, i.e. the node imported cleanly."""
    try:
        code, body = _request(
            base + "/object_info/" + urllib.parse.quote(node_class), timeout=30
        )
        if code != 200:
            return False
        return node_class in json.loads(body)
    except (OSError, json.JSONDecodeError):
        return False


def _wait_for_object_info(
    base: str, node_class: str, emit: Callable[[str], None],
) -> bool:
    deadline = time.monotonic() + config.COMFYUI_MANAGER_VERIFY_TIMEOUT
    while time.monotonic() < deadline:
        if _object_info_has_class(base, node_class):
            return True
        time.sleep(3)
    return False


def _manager_history(base: str) -> Optional[bytes]:
    """Raw Manager task history for our client, or None if the ask failed."""
    try:
        code, body = _request(
            base + "/v2/manager/queue/history?client_id="
            + urllib.parse.quote(_MANAGER_CLIENT_ID),
            timeout=20,
        )
        return body if code == 200 else None
    except OSError:
        return None


def _dump_manager_history(base: str, emit: Callable[[str], None]) -> Optional[bytes]:
    """Best-effort: log the Manager task history for our client on failure."""
    body = _manager_history(base)
    if body is not None:
        emit(f"manager task history: {body.decode('utf-8', 'replace')[:1000]}")
    return body


def _history_task_status(body: Optional[bytes]) -> str:
    """status_str of our install task, or "" when the history has none.
    Only our own client's tasks are in there and we post exactly one."""
    if not body:
        return ""
    match = re.search(
        r'["\']status_str["\']\s*:\s*["\'](\w+)["\']',
        body.decode("utf-8", "replace").lower(),
    )
    return match.group(1) if match else ""


def _history_blames_the_registry(body: Optional[bytes]) -> bool:
    """True when Manager recorded a network/registry failure rather than a
    dependency problem. The install downloads from api.comfy.org, and an
    outage there is not a verdict on our image."""
    if not body:
        return False
    text = body.decode("utf-8", "replace").lower()
    # Spacing depends on how the Manager serialized it, so do not match on it.
    if not re.search(r'["\']status_str["\']\s*:\s*["\']error["\']', text):
        return False
    return any(
        marker in text
        for marker in (
            "api.comfy.org", "connection", "timed out", "timeout",
            "temporary failure in name resolution", "name or service not known",
            "ssl", "502 bad gateway", "503 service", "504 gateway",
            "remote end closed", "max retries exceeded",
        )
    )


def _torch_fingerprint(base: str) -> Optional[tuple]:
    """torch as ComfyUI sees it: the version string (with its +cuXXX build) and
    the device types it ended up on. The venv is --system-site-packages, so a
    node dependency that drags its own torch into the venv shadows the baked
    one; the node still imports, and only this shows it."""
    try:
        code, body = _request(base + "/system_stats", timeout=15)
        if code != 200:
            return None
        stats = json.loads(body)
    except (OSError, json.JSONDecodeError):
        return None
    version = (stats.get("system") or {}).get("pytorch_version")
    types = sorted(str(device.get("type")) for device in (stats.get("devices") or []))
    # An unexpected shape must not read as "nothing changed" on both sides.
    if not version or not types:
        return None
    return (version, types)


def _manager_queue_status(base: str) -> Optional[dict]:
    """Manager's queue counters for our client, or None if the ask failed."""
    url = (
        base + "/v2/manager/queue/status?client_id="
        + urllib.parse.quote(_MANAGER_CLIENT_ID)
    )
    try:
        code, body = _request(url, timeout=15)
        return json.loads(body) if code == 200 else None
    except (OSError, json.JSONDecodeError):
        return None


def _manager_task_landed(base: str) -> bool:
    """Did our task reach the queue? Asked only after queue/task times out,
    because the counters are filtered by our own client_id."""
    deadline = time.monotonic() + config.COMFYUI_MANAGER_QUEUE_TIMEOUT
    while time.monotonic() < deadline:
        status = _manager_queue_status(base)
        if status and (
            status.get("total_count", 0) > 0
            or status.get("done_count", 0) > 0
            or status.get("is_processing", False)
        ):
            return True
        time.sleep(5)
    return False


def _manager_install_node(
    base: str, node: dict, emit: Callable[[str], None],
) -> tuple[bool, str]:
    """Queue a Manager install task, start the worker, and wait for it to drain.
    Returns (ok, detail); detail starts with the UNVERIFIED marker when the
    pod stopped answering rather than the install going wrong."""
    version = node.get("selected_version", "latest")
    task = {
        "ui_id": f"smoke-{int(time.time())}",
        "client_id": _MANAGER_CLIENT_ID,
        "kind": "install",
        "params": {
            "id": node["id"],
            "version": version,
            "selected_version": version,
            # `cache` reads the prebaked registry DB; the archive still downloads.
            "mode": "cache",
            "channel": "default",
        },
    }
    body = b""
    try:
        code, body = _request(
            base + "/v2/manager/queue/task", json.dumps(task).encode(),
            timeout=config.COMFYUI_MANAGER_QUEUE_TIMEOUT,
        )
    except OSError as exc:
        # The handler queues the task after that snapshot, so a timeout here
        # does not mean it was lost. Posting again would install twice.
        emit(f"queue/task did not answer ({type(exc).__name__}), checking the queue")
        if not _manager_task_landed(base):
            return False, (
                f"{MANAGER_UNVERIFIED}: queue/task never answered and no task "
                f"reached the queue ({type(exc).__name__}: {exc})"
            )
        emit("the task reached the queue despite the timeout")
        code = 200
    if code != 200:
        return False, f"queue/task returned HTTP {code}: {body[:300]!r}"

    # Empty JSON body so the CSRF guard sees a non-simple Content-Type.
    # Idempotent (200 started, 201 already running), so retrying is safe.
    last_error = ""
    for attempt in range(1, 4):
        try:
            code, _ = _request(
                base + "/v2/manager/queue/start", b"",
                timeout=config.COMFYUI_MANAGER_QUEUE_TIMEOUT,
            )
            break
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            emit(f"queue/start did not answer ({last_error}), attempt {attempt}/3")
            time.sleep(5)
    else:
        return False, f"{MANAGER_UNVERIFIED}: queue/start never answered ({last_error})"
    if code not in (200, 201):
        return False, f"queue/start returned HTTP {code}"

    deadline = time.monotonic() + config.COMFYUI_MANAGER_INSTALL_TIMEOUT
    status: dict = {}
    while time.monotonic() < deadline:
        status = _manager_queue_status(base) or {}
        # done_count only says the task left the queue, not that it succeeded;
        # the object_info check after reboot is the real pass/fail gate.
        if (
            status.get("done_count", 0) >= 1
            and status.get("total_count", 0) == 0
            and not status.get("is_processing", False)
        ):
            emit("install task finished")
            return True, ""
        time.sleep(3)
    return False, (
        f"install task did not finish in "
        f"{config.COMFYUI_MANAGER_INSTALL_TIMEOUT}s (last={status})"
    )


def _manager_reboot(base: str, emit: Callable[[str], None]) -> None:
    """Request a ComfyUI restart. The server execs itself, so a dropped
    connection here is the expected outcome, not a failure."""
    try:
        code, _ = _request(base + "/v2/manager/reboot", b"", timeout=15)
        emit(f"reboot requested (HTTP {code})")
    except OSError as exc:
        emit(f"reboot requested (connection closed: {type(exc).__name__})")


def run_comfyui_manager_check(
    pod_id: str, on_line: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Install a custom node via ComfyUI-Manager, reboot, verify it loads, and
    verify the install did not replace the baked torch."""
    emit = on_line or (lambda _message: None)
    base = _base_url(pod_id)
    emit(f"ComfyUI-Manager install check via proxy: {base}")
    try:
        node = _load_json(config.COMFYUI_MANAGER_NODE_MANIFEST)
    except OSError as exc:
        return False, f"could not read manager node manifest: {exc}"
    node_class = node.get("verify_class")
    if not node.get("id") or not node_class:
        return False, "manager node manifest needs 'id' and 'verify_class'"

    if not _wait_for_system_stats(base, emit):
        return False, "ComfyUI /system_stats unavailable"
    if not _wait_for_manager(base, emit):
        return False, "ComfyUI-Manager API unavailable"

    if _object_info_has_class(base, node_class):
        return False, f"node class {node_class} already present before install"

    before = _torch_fingerprint(base)
    if before is None:
        return False, "could not read torch state from /system_stats before install"
    emit(f"torch before install: {before[0]} on {','.join(before[1])}")

    emit(f"installing {node['id']}@{node.get('selected_version', 'latest')} via Manager...")
    ok, detail = _manager_install_node(base, node, emit)
    if not ok:
        history = _dump_manager_history(base, emit)
        if detail.startswith(MANAGER_UNVERIFIED):
            return False, detail
        if _history_blames_the_registry(history):
            return False, (
                f"{MANAGER_UNVERIFIED}: the ComfyUI registry or the network "
                f"failed the install, not a dependency problem ({detail})"
            )
        return False, f"Manager install failed for {node['id']}: {detail}"

    # Manager keeps task history in memory only and the reboot below execv's
    # the server, so read the install result while it still exists. The queue
    # drains either way, so this is the only place a failed install is visible.
    history = _manager_history(base)
    status = _history_task_status(history)
    if status and status != "success":
        emit(f"manager task history: {history.decode('utf-8', 'replace')[:1000]}")
        if _history_blames_the_registry(history):
            return False, (
                f"{MANAGER_UNVERIFIED}: the ComfyUI registry or the network "
                f"failed the install of {node['id']}"
            )
        return False, f"Manager reported the install of {node['id']} as {status}"

    emit("rebooting ComfyUI to activate the node...")
    _manager_reboot(base, emit)
    # Give the server a moment to drop before we start polling for it to return.
    time.sleep(10)
    if not _wait_for_system_stats(base, emit):
        return False, "ComfyUI did not come back after reboot"

    emit(f"verifying node class {node_class} is importable...")
    if not _wait_for_object_info(base, node_class, emit):
        # No history to consult here: the reboot cleared it. The Manager said
        # the install succeeded, so a missing class is the image's problem.
        return False, f"node class {node_class} not available after install+reboot"

    # The point of the whole step: the dependency resolved against the baked
    # torch rather than pulling its own into the venv.
    after = _torch_fingerprint(base)
    if after is None:
        return False, "could not read torch state from /system_stats after install"
    if after != before:
        return False, f"the install changed torch: {before} -> {after}"
    emit(f"torch unchanged: {after[0]} on {','.join(after[1])}")

    emit("COMFYUI MANAGER CHECK OK")
    return True, f"installed + activated {node['id']} ({node_class}), torch unchanged"
