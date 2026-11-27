"""ComfyUI public-proxy smoke and end-to-end generation checks."""

from __future__ import annotations

import base64
import json
import os
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
