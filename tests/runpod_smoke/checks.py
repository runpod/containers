"""SSH-based health and functional checks.

  * ssh_probe — one-shot connection probe, used as the real readiness signal
  * cuda_check_command / run_cuda_check — torch.cuda or nvidia-smi assertion
  * jupyter_check_command / run_jupyter_check — in-pod Jupyter probe over SSH
  * run_jupyter_proxy_check — public proxy probe from the test machine
 * REST API v2 log helpers / dump_pod_logs — diagnose failures before termination

Selection of the CUDA check is driven by the IMAGE REF, not the manifest
group name: new groups added in the future won't silently skip the check.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from . import api, config
from .log import log


# Error string returned by every helper that shells out to `ssh` and fails
# because the binary isn't on $PATH. Centralised so the message stays
# identical across helpers (callers grep for it in logs).
_SSH_BINARY_NOT_FOUND = "ssh binary not found"


# ---------------------------------------------------------------------------
# SSH plumbing
# ---------------------------------------------------------------------------


def _resolve_ssh_identity() -> Optional[str]:
    """Find the SSH private key to use for the runpodctl-managed PUBLIC_KEY.

    Order of preference:
      1. RUNPOD_SSH_KEY env var (explicit override)
      2. runpodctl-managed key at ~/.runpod/ssh/runpodctl-ssh-key
      3. Standard ssh defaults (~/.ssh/id_ed25519, ~/.ssh/id_rsa, ssh-agent)
    Returns the path if a non-default key was found, else None (let ssh
    pick a default from its standard search path / ssh-agent)."""
    if config.SSH_IDENTITY:
        return config.SSH_IDENTITY if os.path.isfile(config.SSH_IDENTITY) else None
    for candidate in (
        "~/.runpod/ssh/runpodctl-ssh-key",
        "~/.runpod/runpodctl-ssh-key",
        "~/.ssh/runpodctl-ssh-key",
    ):
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


# How to address each endpoint. Direct SSH lands in the container as root;
# the RunPod proxy needs an opaque routing token and a pseudo-terminal, and
# the API hands us the exact invocation in `ssh.proxy.command`, so we build
# on that instead of guessing. `pod.wait_for_running` registers what it
# found; everything else keeps identifying endpoints by (host, port).
_SSH_ENDPOINTS: dict[tuple[str, int], tuple[str, str, bool]] = {}


def set_ssh_endpoint(
    host: str, port: int, user: str, command: str = "", *, pty: bool = False,
) -> None:
    if host and port and user:
        _SSH_ENDPOINTS[(host, int(port))] = (user, command or "", pty)


def ssh_user_for(host: str, port: int) -> str:
    entry = _SSH_ENDPOINTS.get((host, int(port)))
    return entry[0] if entry else "root"


def _ssh_command_prefix(host: str, port: int) -> list[str]:
    """Build the `ssh ... <user>@<host>` prefix common to all SSH calls.

    For a registered endpoint the API's own invocation is the base, with the
    flags its description tells us to add (`-i`, `-o StrictHostKeyChecking`)
    plus `-tt` when the endpoint insists on a terminal. Everything else gets
    the plain `root@host -p port` form.
    """
    user, api_command, pty = _SSH_ENDPOINTS.get(
        (host, int(port)), ("root", "", False)
    )
    identity = _resolve_ssh_identity()
    target = f"{user}@{host}"
    if api_command:
        # Keep only the target from the API string: the flags we add below
        # are the ones it documents as missing, and re-using its argv
        # verbatim would fight with SSH_OPTS.
        parts = shlex.split(api_command)
        target = next((p for p in parts[1:] if "@" in p), target)
    cmd = ["ssh", *config.SSH_OPTS]
    if pty:
        # -tt, not -t: the local stdin is not a terminal under subprocess,
        # and single -t silently declines to allocate one in that case.
        cmd.append("-tt")
    if int(port) != 22:
        cmd.extend(["-p", str(port)])
    if identity:
        cmd.extend(["-i", identity])
    cmd.append(target)
    return cmd


def _strip_cr(text: str) -> str:
    """A PTY turns every \\n into \\r\\n; undo that so parsing and logs match
    what a direct, terminal-less connection would have produced."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def ssh_probe(host: str, port: int, timeout: int = 8) -> tuple[bool, str]:
    """One-shot SSH connection attempt. Returns (success, stderr_excerpt).
    Used as the real container-readiness signal."""
    cmd = [*_ssh_command_prefix(host, port), "echo", "ready"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "ssh probe timed out"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    if r.returncode == 0 and "ready" in r.stdout:
        return True, ""
    return False, (r.stderr or r.stdout).strip()[:200]


# ---------------------------------------------------------------------------
# CUDA / GPU functional check
# ---------------------------------------------------------------------------

# Image-tag substrings/patterns we treat as "this image expects a GPU
# runtime" (NVIDIA CUDA or AMD ROCm). Kept loose on purpose — the worst
# case for a false positive is running nvidia-smi on a CPU pod, which just
# returns non-zero and surfaces as a FAIL we'd want to see anyway.
_GPU_TAG_RE = re.compile(
    # 'cuda1281', 'cuda1300', or the bare word 'cuda' (e.g. nvidia/cuda:...)
    r"\bcuda\b|\bcuda\d"
    # 'cu1281', 'cu1290' short form. Boundary prevents matching 'cube',
    # 'cute', etc. — we require a digit immediately after 'cu'.
    r"|(?:^|[^a-z0-9])cu\d"
    # AMD ROCm tag fragments: 'rocm', 'rocm644'.
    r"|\brocm",
    re.IGNORECASE,
)

# Image-name/tag markers that imply PyTorch is installed in the *system*
# Python (i.e. `python -c "import torch"` will work over SSH).
# Deliberately does NOT match autoresearch: its torch lives in
# /opt/autoresearch/.venv (uv-managed) and isn't on sys.path for the
# system interpreter we ssh into.
_TORCH_TAG_RE = re.compile(
    # 'pytorch' anywhere in name or tag covers runpod/pytorch,
    # runpod/nvidia-pytorch, and base images with -pytorch251-style tags.
    r"\bpytorch"
    # Tag fragments like 'torch260', 'torch271' — short form some images use.
    r"|(?:^|[^a-z0-9])torch\d",
    re.IGNORECASE,
)

# Image-tag markers for AMD ROCm runtimes. Matched BEFORE the torch regex
# so that ROCm-pytorch images (which inherit from rocm/pytorch:* and keep
# torch in a conda env not visible to the system `python`) take the
# rocm-smi path instead of falling into the import-torch path and failing
# with a misleading "ModuleNotFoundError".
_ROCM_TAG_RE = re.compile(r"\brocm", re.IGNORECASE)


def _image_expects_gpu(image: str) -> bool:
    """True if the image ref implies a GPU runtime (CUDA or ROCm) inside."""
    return bool(_GPU_TAG_RE.search(image))


def _image_expects_torch(image: str) -> bool:
    """True if the image ref implies PyTorch is importable from system Python."""
    return bool(_TORCH_TAG_RE.search(image))


def _image_expects_rocm(image: str) -> bool:
    """True if the image ref implies an AMD ROCm runtime."""
    return bool(_ROCM_TAG_RE.search(image))


def fetch_pod_cuda_version(pod_id: str, attempts: int = 3) -> str:
    """Return the CUDA version the host reported, e.g. '13.0'.

    `min_cuda_version` is only a floor, so the scheduler may place the pod on
    any host at or above it — this reports what it actually got, which is the
    point of a compatibility matrix.

    Nullable per the API: CPU pods and hosts that never reported one give ''.
    Retried a few times because the value only lands once the scheduler has
    assigned a machine. Reporting only — never turns a PASS into a FAIL.
    """
    for attempt in range(1, attempts + 1):
        status, data = api.request("GET", f"/pods/{pod_id}", timeout=15)
        cuda = data.get("cudaVersion") if isinstance(data, dict) else None
        if 200 <= status < 300 and cuda:
            return str(cuda).strip()
        if attempt < attempts:
            time.sleep(2)
    return ""


def cuda_check_command(image: str) -> str:
    """Return a shell command that functionally validates the GPU/CUDA stack
    for a given image, or '' to skip the check (CPU images).

    Selection is driven by the IMAGE REF (not the manifest group name) so
    new manifest groups added in the future won't silently skip the check.

    Logic (first match wins):
        - has 'rocm' in ref                          -> run rocm-smi check
          (AMD GPUs; runpod/base ROCm-pytorch images inherit from
          rocm/pytorch:* where torch lives in a conda env not visible to
          the system `python`, so the torch.cuda path would falsely fail
          with ModuleNotFoundError)
        - has 'pytorch' / 'torch\\d' in ref          -> run torch.cuda check
          (covers runpod/pytorch, runpod/nvidia-pytorch — NVIDIA stack)
        - has 'cuda' / 'cu\\d' only                  -> run nvidia-smi check
          (runpod/base GPU tags and autoresearch — torch in venv not
          visible to system python)
        - none of the above                          -> CPU image, no check

    The returned command MUST exit non-zero on failure so the SSH call can
    detect it. Output is captured for the run report.
    """
    if _image_expects_rocm(image):
        # AMD ROCm path. `rocm-smi` is the AMD counterpart to nvidia-smi
        # and ships in every official rocm/* base image. We assert it
        # finds at least one GPU by grepping for the GPU table header.
        return (
            "set -e; "
            "rocm-smi --showproductname --showmeminfo vram; "
            "rocm-smi --showid | grep -qE '^GPU\\[[0-9]+\\]' "
            "  || { echo 'FAIL: rocm-smi reported no GPUs'; exit 1; }; "
            "if command -v hipcc >/dev/null; then "
            "  hipcc --version | head -n 2; "
            "else "
            "  echo 'hipcc not in PATH (HIP toolkit may be runtime-only)'; "
            "fi"
        )

    if _image_expects_torch(image):
        # Use `python` (the runpod/base symlink /usr/local/bin/python ->
        # /usr/bin/python3.12), NOT `python3`. On Ubuntu 22.04 system
        # `python3` resolves to python3.10 — but pytorch/Dockerfile
        # installs torch via `python -m pip`, so torch only exists in
        # python3.12's site-packages. On 24.04 they happen to coincide.
        # Using `python` is portable.
        return (
            "python - <<'PY'\n"
            "import sys, torch\n"
            "assert torch.cuda.is_available(), 'torch.cuda.is_available() returned False'\n"
            "n = torch.cuda.device_count()\n"
            "assert n > 0, 'torch.cuda.device_count() == 0'\n"
            "name = torch.cuda.get_device_name(0)\n"
            "cap = torch.cuda.get_device_capability(0)\n"
            "print(f'torch={torch.__version__} cuda={torch.version.cuda} '\n"
            "      f'gpus={n} dev0={name!r} compute={cap[0]}.{cap[1]}')\n"
            "# Tiny tensor-on-GPU sanity check: catches driver bugs that pass\n"
            "# is_available() but fail on actual memory ops.\n"
            "x = torch.ones(64, 64, device='cuda')\n"
            "y = (x @ x).sum().item()\n"
            "assert y == 64*64*64, f'matmul gave {y}, expected {64*64*64}'\n"
            "print('matmul ok')\n"
            "PY"
        )

    if _image_expects_gpu(image):
        # GPU image without system-Python torch (raw base, autoresearch's
        # uv-venv'd torch, etc.). Verify the toolkit + driver respond to a
        # real query — more than just an nvidia-smi banner.
        return (
            "set -e; "
            "nvidia-smi -L; "
            "nvidia-smi --query-gpu=name,driver_version,memory.total "
            "  --format=csv,noheader; "
            "if command -v nvcc >/dev/null; then "
            "  nvcc --version | tail -n 2; "
            "else "
            "  echo 'nvcc not in PATH (CUDA toolkit may be runtime-only)'; "
            "fi"
        )

    # No GPU/torch markers — treat as CPU image. Boot + dwell is the only
    # gate; no extra functional check to run.
    return ""


def run_cuda_check(host: str, port: int, image: str) -> tuple[bool, str]:
    """Run the GPU/CUDA functional check inside the pod over SSH.
    Returns (ok, output). ok=True when:
      * the image has no GPU check defined (treated as pass), OR
      * the remote command exits 0.
    output contains stdout+stderr for inclusion in the run log."""
    cmd = cuda_check_command(image)
    if not cmd:
        return True, "(no GPU check for this image)"
    ssh_cmd = [*_ssh_command_prefix(host, port), cmd]
    try:
        r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "cuda check timed out after 60s"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    combined = _strip_cr(r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


# ---------------------------------------------------------------------------
# Jupyter checks (opt-in)
# ---------------------------------------------------------------------------


def jupyter_check_command(timeout: int) -> str:
    """Shell snippet (run via SSH on the pod) that verifies Jupyter Lab is
    actually running and answers HTTP with the token we set via env.

    Why both `jupyter server list` AND a `curl`: the list catches the silent
    `python3 -m jupyter` failure mode (server never started — list is empty
    even though start.sh printed 'Jupyter Lab started'); the curl catches
    "process is alive but http endpoint is wedged" or "token mismatch".

    Polls for up to `timeout` seconds because start.sh launches Jupyter in
    background via `nohup ... &` and exits without waiting; the HTTP port
    typically becomes reachable a few seconds after the pod logs say it is.
    """
    return (
        "set -e; "
        # Wait for the HTTP port to open. Don't rely on `jupyter` CLI being
        # in PATH yet (the binary IS in PATH from the base image, but the
        # server takes a few seconds to bind). Use raw /dev/tcp instead so
        # we don't need nc / curl just to detect "listening".
        f"for i in $(seq 1 {timeout}); do "
        "  if (echo > /dev/tcp/127.0.0.1/8888) 2>/dev/null; then break; fi; "
        "  sleep 1; "
        "done; "
        # Server should appear in `jupyter server list`. If start.sh used
        # the wrong python interpreter, this is empty.
        "echo '--- jupyter server list ---'; "
        "OUT=$(jupyter server list 2>&1 || true); "
        "echo \"$OUT\"; "
        "echo \"$OUT\" | grep -qE 'http://[^ ]*:8888' "
        "  || { echo 'FAIL: no Jupyter server listening on :8888'; exit 1; }; "
        # API responds with our token. /api/status is a tiny endpoint that
        # returns 200 + JSON when the server is healthy AND auth passes.
        "echo '--- curl /api/status ---'; "
        f"curl -sS --max-time 10 -o /tmp/_jupyter_status "
        f"  -w 'http=%{{http_code}}\\n' "
        f"  \"http://127.0.0.1:8888/api/status?token={config.JUPYTER_TEST_PASSWORD}\" "
        "  || { echo 'FAIL: curl to :8888 failed'; exit 1; }; "
        "cat /tmp/_jupyter_status; echo; "
        "grep -qE '^http=200' /tmp/_jupyter_status 2>/dev/null "
        "  || grep -qE '\"started\"' /tmp/_jupyter_status "
        "  || { echo 'FAIL: /api/status did not return 200 with valid token'; "
        "       exit 1; }; "
        "echo 'jupyter check OK'"
    )


def run_jupyter_check(host: str, port: int) -> tuple[bool, str]:
    """SSH into the pod and run the jupyter probe against 127.0.0.1:8888.

    This validates the IN-POD side: start.sh launched Jupyter with the
    right interpreter, server bound to :8888, our token works.

    Returns (ok, output). ok=False when the SSH call itself failed, OR
    when jupyter probe exited non-zero (server not running / wrong token
    / API not healthy)."""
    cmd = jupyter_check_command(config.JUPYTER_WAIT_TIMEOUT)
    ssh_cmd = [*_ssh_command_prefix(host, port), cmd]
    # SSH command has its own grace loop (JUPYTER_WAIT_TIMEOUT) plus a 10s
    # curl; pad the outer timeout to leave room for SSH handshake.
    outer_timeout = config.JUPYTER_WAIT_TIMEOUT + 30
    try:
        r = subprocess.run(
            ssh_cmd, capture_output=True, text=True, timeout=outer_timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"jupyter check timed out after {outer_timeout}s"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    combined = _strip_cr(r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


# ---------------------------------------------------------------------------
# Generic per-port checks (test_ports manifest field)
# ---------------------------------------------------------------------------

def port_check_command(test_port: int, wait_timeout: int) -> str:
    """Wait for localhost HTTP readiness; 4xx is a valid app response."""
    return (
        "set -e; "
        f"echo 'Probing 127.0.0.1:{test_port} (timeout {wait_timeout}s)...'; "
        "CODE=pending; "
        f"for i in $(seq 1 {wait_timeout}); do "
        f"  if (echo > /dev/tcp/127.0.0.1/{test_port}) 2>/dev/null; then "
        f"    CODE=$(curl -sS --max-time 5 -o /dev/null "
        f"      -w '%{{http_code}}' 'http://127.0.0.1:{test_port}/' "
        "      || echo 'curl_failed'); "
        "    case \"$CODE\" in "
        f"      [1234]*) echo \"port {test_port} responsive after $i"
        "s: http=$CODE\"; break ;; "
        "      *) ;; "
        "    esac; "
        "  fi; "
        "  if [ $((i % 30)) -eq 0 ]; then "
        f"    echo \"  ...still probing :{test_port} at ${{i}}s/{wait_timeout}s "
        "(last code=$CODE)\"; "
        "  fi; "
        "  sleep 1; "
        "done; "
        "case \"$CODE\" in "
        f"  [1234]*) echo 'port {test_port} OK' ;; "
        f"  pending) echo 'FAIL: nothing ever listened on 127.0.0.1:{test_port} "
        f"within {wait_timeout}s'; exit 1 ;; "
        f"  *) echo \"FAIL: port {test_port} never returned HTTP <500 "
        f"within {wait_timeout}s (last code: $CODE)\"; exit 1 ;; "
        "esac"
    )


def run_port_check(
    host: str,
    port: int,
    test_port: int,
    on_line: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Run the in-pod fallback probe with live progress and a hard timeout."""
    ssh_cmd = [
        *_ssh_command_prefix(host, port),
        port_check_command(test_port, config.PORT_WAIT_TIMEOUT),
    ]
    outer_timeout = config.PORT_WAIT_TIMEOUT + 60
    try:
        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    assert proc.stdout is not None

    timed_out = [False]

    def kill_on_timeout() -> None:
        timed_out[0] = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(outer_timeout, kill_on_timeout)
    watchdog.daemon = True
    watchdog.start()
    last_line = ""
    try:
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\n")
            if line:
                if on_line:
                    on_line(line)
                last_line = line
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception as exc:  # noqa: BLE001
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"port {test_port} check errored: {exc}"
    finally:
        watchdog.cancel()

    if timed_out[0]:
        return False, (
            f"port {test_port} check wall-clock timeout after {outer_timeout}s"
        )
    return proc.returncode == 0, last_line


def _proxy_status_ok(code: int) -> bool:
    """A service is healthy through the public proxy only on HTTP 200."""
    return code == 200


def run_port_proxy_check(pod_id: str, test_port: int) -> tuple[bool, str]:
    """Probe a generic HTTP service through RunPod's public proxy."""
    url = f"https://{pod_id}-{test_port}.proxy.runpod.net/"
    deadline = time.monotonic() + config.PORT_PROXY_TIMEOUT
    lines = [f"GET {url}"]
    last_error = ""
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "runpod-smoke-test/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                code = response.status
                body = response.read(256).decode("utf-8", errors="replace")
                lines.append(
                    f"attempt #{attempt}: HTTP {code} body={body[:160]!r}"
                )
                if _proxy_status_ok(code):
                    return True, "\n".join(lines)
                last_error = f"HTTP {code}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            lines.append(f"attempt #{attempt}: {last_error}")
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            lines.append(f"attempt #{attempt}: {last_error}")
        time.sleep(5)
    lines.append(
        f"FAIL: no HTTP 200 via proxy after {config.PORT_PROXY_TIMEOUT}s "
        f"({attempt} attempts), last error: {last_error}"
    )
    return False, "\n".join(lines)


def run_jupyter_proxy_check(pod_id: str) -> tuple[bool, str]:
    """Hit `https://<pod-id>-8888.proxy.runpod.net/api/status?token=admin`
    from the test machine. Verifies that:

      1. RunPod's public proxy has the pod registered for port 8888.
         If the port was exposed as `8888/tcp` instead of `8888/http`, the
         proxy never wires it up and this fails. The SSH-side check would
         still pass — that's exactly the kind of misconfiguration the
         end-user would hit when they tried to open Jupyter from the UI.
      2. Jupyter is reachable end-to-end, not just on localhost.

    Retries for up to JUPYTER_PROXY_TIMEOUT seconds because the proxy is
    eventually-consistent: a freshly-created pod may not be in its routing
    table for ~10–30s. Returns (ok, multi-line log).
    """
    url = (
        f"https://{pod_id}-8888.proxy.runpod.net/api/status"
        f"?token={config.JUPYTER_TEST_PASSWORD}"
    )
    # Same URL with the token stripped — used in log lines so we never
    # write the bearer token to stdout / CI logs. The real `url` (with
    # token) only ever goes to urlopen.
    redacted_url = (
        f"https://{pod_id}-8888.proxy.runpod.net/api/status?token=<redacted>"
    )
    deadline = time.monotonic() + config.JUPYTER_PROXY_TIMEOUT
    lines = [f"GET {redacted_url}"]
    last_err = ""
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "runpod-smoke-test/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
                body = resp.read(2048).decode("utf-8", errors="replace")
                lines.append(
                    f"attempt #{attempt}: HTTP {code} body={body[:200]}"
                )
                if code == 200:
                    return True, "\n".join(lines)
                last_err = f"HTTP {code}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
            lines.append(f"attempt #{attempt}: {last_err}")
        except OSError as exc:
            # urllib.error.URLError and the builtin TimeoutError both derive
            # from OSError, so this single clause covers connection refused,
            # DNS failures, socket timeouts, and 'No route to host' alike.
            last_err = f"{type(exc).__name__}: {exc}"
            lines.append(f"attempt #{attempt}: {last_err}")
        time.sleep(5)

    lines.append(
        f"FAIL: proxy unreachable after {config.JUPYTER_PROXY_TIMEOUT}s "
        f"({attempt} attempts), last error: {last_err}"
    )
    return False, "\n".join(lines)


# ---------------------------------------------------------------------------
# Container logs via REST API (v2) + error scan
# ---------------------------------------------------------------------------

def fetch_pod_logs_api(
    pod_id: str,
    tail: int = 0,
    source: str = "container",
    deadline_sec: int = 15,
) -> Optional[list[str]]:
    """Fetch the SSE backfill from `GET /v2/pods/{id}/logs`.

    The endpoint stays open for live logs. Stop after its historical
    backfill is drained (socket idle) or the deadline expires.
    """
    api_key = api.load_api_key()
    if not api_key:
        return None
    tail = tail or config.LOG_API_TAIL
    req = urllib.request.Request(
        f"https://api.runpod.io/v2/pods/{pod_id}/logs?source={source}&tail={tail}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
            "User-Agent": "test-images.py/1.0 (+runpod-smoketest)",
        },
    )
    lines: list[str] = []
    deadline = time.monotonic() + deadline_sec
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            while time.monotonic() < deadline:
                try:
                    raw = resp.readline()
                except OSError:
                    break
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                try:
                    payload = json.loads(text[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                line = payload.get("line")
                if line is not None:
                    lines.append(line.rstrip())
    except (urllib.error.HTTPError, OSError) as exc:
        log(f"  (log API fetch failed: {exc})", indent=2)
        return None
    return lines


def system_log_errors(pod_id: str, max_lines: int = 20) -> Optional[list[str]]:
    """Return error-marker lines from the host-side REST system-log stream."""
    lines = fetch_pod_logs_api(pod_id, source="system")
    if lines is None:
        return None
    pattern = re.compile(config.SYS_LOG_ERROR_PATTERN, re.IGNORECASE)
    return [line for line in lines if pattern.search(line)][:max_lines]


# `nvidia-container-cli` aborts the prestart hook when the image's
# NVIDIA_REQUIRE_CUDA floor is above the host driver.
_HOST_INCOMPATIBLE_RE = re.compile(
    r"nvidia-container-cli:[^\n]*requirement error"
    r"|unsatisfied condition:\s*cuda",
    re.IGNORECASE,
)
_CUDA_CONDITION_RE = re.compile(
    r"unsatisfied condition:\s*(cuda\s*[<>=!]+\s*[\d.]+)", re.IGNORECASE
)


def host_incompatibility(sys_errors: Optional[list[str]]) -> str:
    """Summarize a container-init rejection, or '' if there wasn't one.

    Unlike a dead host, this verdict is deterministic: the same image on the
    same pinned CUDA is rejected by every host, so the caller must not retry
    other instance types.
    """
    for line in sys_errors or []:
        if not _HOST_INCOMPATIBLE_RE.search(line):
            continue
        match = _CUDA_CONDITION_RE.search(line)
        return match.group(1) if match else line.strip()[:200]
    return ""


_LOG_SCAN_ATTEMPTS = 3
_LOG_SCAN_RETRY_SLEEP_SEC = 10


def scan_pod_logs_for_errors(pod_id: str) -> tuple[bool, str]:
    """Scan container stdout for configured errors.

    Empty API responses are retried and then fail as unverified: every
    supported image emits boot logs, so zero lines cannot prove a clean boot.
    """
    if not api.load_api_key():
        return True, "(no API key — log scan skipped)"
    failures: list[str] = []
    for attempt in range(1, _LOG_SCAN_ATTEMPTS + 1):
        lines = fetch_pod_logs_api(pod_id)
        if lines:
            break
        failures.append(
            f"attempt #{attempt}: "
            + ("fetch failed" if lines is None else "0 log lines")
        )
        if attempt < _LOG_SCAN_ATTEMPTS:
            time.sleep(_LOG_SCAN_RETRY_SLEEP_SEC)
    else:
        return False, (
            "log scan UNVERIFIED — the log API returned no container logs "
            f"after {_LOG_SCAN_ATTEMPTS} attempts ({'; '.join(failures)})"
        )

    pattern = re.compile(config.LOG_ERROR_PATTERN, re.IGNORECASE)
    matches = [line for line in lines if pattern.search(line)]
    if not matches:
        return True, f"scanned {len(lines)} log lines — no error markers"
    report = [
        f"scanned {len(lines)} log lines — "
        f"{len(matches)} matched /{config.LOG_ERROR_PATTERN}/i:"
    ]
    report.extend(f"  {line}" for line in matches[:40])
    if len(matches) > 40:
        report.append(f"  ... (+{len(matches) - 40} more)")
    return False, "\n".join(report)


# ---------------------------------------------------------------------------
# Diagnostic log fetch
# ---------------------------------------------------------------------------


def _gpu_smi_block(image: str) -> str:
    """Pick the right vendor SMI for the diagnostic dump.

    This mirrors `cuda_check_command`: ROCm image refs get `rocm-smi`,
    CUDA/GPU image refs get `nvidia-smi`, and CPU images skip the SMI
    section entirely.
    """
    if _image_expects_rocm(image):
        return (
            "echo '=== rocm-smi ==='; "
            "if command -v rocm-smi >/dev/null 2>&1; then "
            "  rocm-smi 2>&1 | head -n 25; "
            "else "
            "  echo '(rocm-smi not in PATH)'; "
            "fi; "
        )
    if _image_expects_gpu(image):
        return (
            "echo '=== nvidia-smi ==='; "
            "if command -v nvidia-smi >/dev/null 2>&1; then "
            "  nvidia-smi 2>&1 | head -n 15; "
            "else "
            "  echo '(nvidia-smi not in PATH)'; "
            "fi; "
        )
    return ""


def fetch_logs_via_ssh(
    host: str, port: int, image: str,
) -> Optional[str]:
    """Fetch the GPU SMI snapshot, the remaining SSH-only diagnostic."""
    if not config.SSH_LOG_FETCH:
        return None
    smi_block = _gpu_smi_block(image)
    if not smi_block:
        return None
    remote_cmd = "set +e; " + smi_block
    cmd = [*_ssh_command_prefix(host, port), remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    if r.returncode == 0 and r.stdout.strip():
        return _strip_cr(r.stdout)
    return f"__SSH_FAILED__\nreturncode={r.returncode}\nstderr: {r.stderr.strip()[:400]}"


def dump_pod_logs(pod_id: str, image: str) -> list[str]:
    """Print metadata, API container logs, system errors, and GPU SMI.

    Returns the system-log error markers so a caller classifying the failure
    can read them without fetching the stream a second time.
    """
    sys_errors: list[str] = []
    status, data = api.request("GET", f"/pods/{pod_id}", timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        api.log_error("(could not fetch pod state)", status, data, indent=2)
        return sys_errors
    ssh = data.get("ssh") or {}
    direct = ssh.get("direct") or {}
    proxy = ssh.get("proxy") or {}
    host, port = direct.get("host"), direct.get("port")
    # Fall back to the proxy so the SMI snapshot still gets fetched on pods
    # that never received a direct TCP port.
    if not (host and port) and proxy.get("host") and proxy.get("username"):
        host, port = proxy.get("host"), proxy.get("port")
        set_ssh_endpoint(
            host, int(port or 0), str(proxy["username"]),
            str(proxy.get("command") or ""), pty=True,
        )

    log(f"--- pod metadata for {pod_id} ---", indent=2)
    for key, val in [
        ("status",           data.get("status")),
        ("cudaVersion",      data.get("cudaVersion")),
        ("dataCenterId",     data.get("dataCenterId")),
        ("cost",             data.get("cost")),
        ("ssh.direct",       f"{host}:{port}" if host and port else None),
        ("ssh.proxy",        proxy.get("host") or None),
        ("image",            data.get("image")),
        ("startedAt",        data.get("startedAt")),
    ]:
        log(f"  {key:20s} = {val!r}", indent=2)

    api_lines = fetch_pod_logs_api(pod_id)
    if api_lines:
        log(f"--- container logs via API ({len(api_lines)} lines) ---", indent=2)
        for line in api_lines:
            log(f"  {line}", indent=2)

    sys_errors = system_log_errors(pod_id) or []
    if sys_errors:
        log(
            f"--- system-log error markers via API ({len(sys_errors)}) ---",
            indent=2,
        )
        for line in sys_errors:
            log(f"  {line}", indent=2)

    if not (host and port):
        log("  (no SSH endpoint yet — skipping GPU SMI fetch)", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return sys_errors

    logs = fetch_logs_via_ssh(host, int(port), image)
    if logs is None:
        return sys_errors
    log(
        f"--- GPU SMI via SSH ({ssh_user_for(host, int(port))}@{host}:{port}) ---",
        indent=2,
    )
    if logs.startswith("__SSH_FAILED__"):
        log("  SSH could not reach the pod:", indent=2)
        for line in logs.splitlines()[1:]:
            log(f"    {line}", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return sys_errors
    for line in logs.splitlines():
        log(f"  {line}", indent=2)
    return sys_errors
