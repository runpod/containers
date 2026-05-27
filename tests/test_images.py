#!/usr/bin/env python3
"""Smoke-test RunPod container images.

Reads a YAML manifest of {image, instance-candidates} pairs, spins up each
image on the first available listed instance, waits for the pod to stay
healthy for DWELL_SEC seconds, then terminates it.

Usage:
    ./test_images.py [path/to/images.yaml] [group_filter]

Requirements: runpodctl (logged in), python3 >= 3.9

Manifest schema (per group):
    images:                list of docker images to test (required)
    instances:             list of GPU display names to try, in priority order
                           (one of `instances:` or `max_price_per_hour:` required)
    max_price_per_hour:    USD/hr budget — auto-pick any GPU at this price or
                           below, cheapest first. Loses to explicit `instances:`
                           if both are set.
    min_vram_gb:           extra filter for budget mode (default 0)
    manufacturer:          'Nvidia' or 'AMD' filter for budget mode (default any)

Env vars (overridable):
    CLOUD_TYPE       SECURE | COMMUNITY                       (default: SECURE)
    DISK_GB          container disk size                      (default: 100)
    RUNPOD_API_KEY   used for GraphQL gpu pricing (read from ~/.runpod/config.toml
                     by default; set this in CI / containers without a config file)
    DWELL_SEC        extra seconds to wait after SSH becomes reachable, then
                     re-probe SSH to catch containers that boot, accept SSH,
                     then crash. Set 0 to skip the re-probe.   (default: 60)
    CREATE_TIMEOUT   max seconds to wait for SSH to become reachable
                                                              (default: 600)
    POLL_INTERVAL    poll cadence for SSH probes              (default: 10)
    MAX_PARALLEL     how many images to smoke-test concurrently. Each worker
                     holds at most one pod, so this caps simultaneous live
                     pods. Keep modest to avoid RunPod rate limits and
                     surprise bills.                          (default: 1)
    CREATE_RETRIES   retry pod-create up to N times on transient RunPod 5xx
                     errors ('Something went wrong', 502/503). Capacity
                     shortages are NOT retried.               (default: 3)
    CREATE_RETRY_BACKOFF  seconds between retries (linear backoff)
                                                              (default: 10)
    STALL_HINT_AFTER seconds without an SSH endpoint before the script prints
                     a hint about slow pulls / possible Docker Hub rate limit
                                                              (default: 180)
    SSH_LOG_FETCH    1/0 — fetch container logs via direct SSH at PASS/FAIL
                                                              (default: 1)
    RUNPOD_SSH_KEY   path to private key matching the PUBLIC_KEY runpodctl
                     injects into pods. Auto-discovered from common locations
                     if not set                              (default: empty)

Per-group functional checks (runs over SSH after the container is reachable):
    pytorch / nvidia-pytorch / rocm   PyTorch sees the GPU, matmul on device
    base_gpu                          nvidia-smi + nvcc respond
    base_cpu                          (skipped — no GPU)
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLOUD_TYPE = os.environ.get("CLOUD_TYPE", "SECURE")
DISK_GB = int(os.environ.get("DISK_GB", "100"))
DWELL_SEC = int(os.environ.get("DWELL_SEC", "60"))
CREATE_TIMEOUT = int(os.environ.get("CREATE_TIMEOUT", "600"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))

# Number of images to smoke-test concurrently. Each worker holds at most one
# pod at a time, so MAX_PARALLEL=3 means up to 3 pods alive simultaneously.
# Keep modest: RunPod has per-account rate limits, and your wallet has limits
# too (DISK_GB * pods * hours can add up).
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "1"))

# How many times to retry pod-create when RunPod returns a transient orchestrator
# error ("Something went wrong", 502/503, etc.). Capacity-shortage errors are
# NOT retried (we move on to the next instance instead).
CREATE_RETRIES = int(os.environ.get("CREATE_RETRIES", "3"))
CREATE_RETRY_BACKOFF = int(os.environ.get("CREATE_RETRY_BACKOFF", "10"))

# How long a pod can sit in "no SSH endpoint yet" before we surface a hint about
# slow pulls / possible Docker Hub rate limit. Doesn't fail the pod — just an
# informational note in the logs.
STALL_HINT_AFTER = int(os.environ.get("STALL_HINT_AFTER", "180"))

# Docker Hub authenticated pulls — without this, RunPod datacenters share an
# anonymous IP pool that hits Docker Hub's `toomanyrequests` rate limit fast.
# Either set REGISTRY_AUTH_ID explicitly, or
# REGISTRY_AUTH_NAME to pick by display name, or the script auto-picks
# the first entry from `runpodctl registry list`.
REGISTRY_AUTH_ID = os.environ.get("REGISTRY_AUTH_ID", "")
REGISTRY_AUTH_NAME = os.environ.get("REGISTRY_AUTH_NAME", "")
AUTO_TERMINATE = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

# Container logs aren't exposed via runpodctl 2.3.0's JSON, so we SSH directly
# to the pod's exposed port 22 (mapped to a random high port on a public IP by
# RunPod) to grab them. The endpoint is discovered from `pod get`'s ssh.ip /
# ssh.port fields once the pod is scheduled.
#   Override SSH_IDENTITY if your key lives in a non-standard location.
#   Set SSH_LOG_FETCH=0 to skip SSH-based log fetching entirely.
SSH_IDENTITY = os.environ.get("RUNPOD_SSH_KEY", "")
SSH_LOG_FETCH = os.environ.get("SSH_LOG_FETCH", "1") == "1"
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=10",
    "-o", "BatchMode=yes",
    "-o", "LogLevel=ERROR",
    # OpenSSH 8.7+ disables ssh-rsa (SHA-1) by default. The sshd inside RunPod
    # base images can still want legacy ssh-rsa for RSA client keys (which is
    # what runpodctl auto-generates), so we re-enable it explicitly.
    "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o", "HostKeyAlgorithms=+ssh-rsa",
]

# Extract CUDA version from image tag. Supports both `cuda1281` and `cu1281`
# (interpreted as 12.8.1). Returns "X.Y" suitable for --min-cuda-version, or
# None for images without an embedded CUDA version (CPU images, ROCm, NGC).
# Anchored with \b so we don't match e.g. 'cudnn'.
CUDA_TAG_RE = re.compile(r"\bcu(?:da)?(\d{2})(\d)(\d)\b", re.IGNORECASE)


def detect_cuda_version(image: str) -> Optional[str]:
    """Parse a CUDA version like '12.8' from an image tag.

    Examples:
        runpod/base:...-cuda1281-ubuntu2204     -> '12.8'
        runpod/pytorch:...-cu1300-torch290-...  -> '13.0'
        runpod/base:...-rocm644-...             -> None
        runpod/base:...-ubuntu2404              -> None
        runpod/nvidia-pytorch:...-25.11         -> None (NGC tag, unknown CUDA)

    Used to populate `--min-cuda-version` so RunPod's scheduler only places
    the pod on a host whose driver supports that CUDA version. Without this,
    a cu13.0 image landing on an older-driver host fails with:
        nvidia-container-cli: requirement error: unsatisfied condition: cuda>=13.0
    """
    m = CUDA_TAG_RE.search(image)
    if not m:
        return None
    major, minor, _patch = m.groups()
    return f"{int(major)}.{int(minor)}"


UNAVAILABLE_RE = re.compile(
    # RunPod-specific phrasings observed in pod-create errors:
    r"no\s+longer\s+any\s+instances\s+available"
    r"|please\s+refresh\s+and\s+try\s+again"
    # Generic capacity-shortage phrasings:
    r"|no\s+(?:machines|capacity|hosts|gpus|instances)\s+available"
    r"|insufficient\s+capacity"
    r"|unavailable"
    r"|out\s+of\s+stock"
    r"|sold\s+out",
    re.IGNORECASE,
)

# Generic "RunPod orchestrator hiccupped" errors that we should retry rather
# than treat as a real failure. These appear when several workers race for the
# same scarce GPU at the same instant, or the API is just transiently flaky.
TRANSIENT_RE = re.compile(
    r"something\s+went\s+wrong"
    r"|please\s+try\s+again\s+later"
    r"|contact\s+support"
    r"|internal\s+server\s+error"
    r"|timeout|timed\s+out"
    r"|502|503|504"
    r"|connection\s+(?:reset|refused)",
    re.IGNORECASE,
)

# Display-name -> runpodctl --gpu-id mapping, populated at startup from
# `runpodctl gpu list --include-unavailable`. Keeps the YAML manifest free of
# RunPod-internal gpuId strings — users only put display names there.
GPU_ID_MAP: dict[str, str] = {}


def resolve_gpu_id(display_name: str) -> str:
    """Map a user-supplied GPU display name to its runpodctl gpuId.

    Tries exact match first, then case-insensitive match (so 'RTX 4070 TI' in
    the manifest still finds 'RTX 4070 Ti' in the RunPod catalog). Falls back
    to the raw input — RunPod will then reject it with a clear error."""
    if display_name in GPU_ID_MAP:
        return GPU_ID_MAP[display_name]
    lowered = display_name.lower()
    for catalog_name, gpu_id in GPU_ID_MAP.items():
        if catalog_name.lower() == lowered:
            return gpu_id
    return display_name


def is_known_gpu(display_name: str) -> bool:
    """Case-insensitive membership check against the discovered GPU catalog."""
    if display_name in GPU_ID_MAP:
        return True
    lowered = display_name.lower()
    return any(name.lower() == lowered for name in GPU_ID_MAP)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log_lock = threading.Lock()
_thread_local = threading.local()
_worker_id_lock = threading.Lock()
_next_worker_id = 0


def ensure_worker_tag() -> None:
    """Assign a stable W<N> tag to the current thread on first use.
    Reused for every job this pool thread runs, so all output from one
    pool worker stays under the same label even when len(jobs) > MAX_PARALLEL.
    """
    global _next_worker_id
    if getattr(_thread_local, "tag", None):
        return
    with _worker_id_lock:
        _next_worker_id += 1
        _thread_local.tag = f"W{_next_worker_id}"


def log(msg: str, indent: int = 0) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    tag = getattr(_thread_local, "tag", "")
    tag_part = f"[{tag}] " if tag else ""
    # Lock so multiple workers' lines don't get interleaved mid-line.
    with _log_lock:
        print(f"[{ts}] {tag_part}{'  ' * indent}{msg}", flush=True)


# ---------------------------------------------------------------------------
# Minimal YAML parser for our specific manifest format
# ---------------------------------------------------------------------------


def parse_manifest(path: Path) -> dict[str, dict]:
    """Parse a fixed-format manifest:

        groupname:
            images:
            - imagename
            instances:                  # explicit list (optional)
            - instance
            max_price_per_hour: 1.0     # OR budget filter (optional)
            min_vram_gb: 16             # extra filter (optional)
            manufacturer: Nvidia        # extra filter (optional)

    Supports both list values (`images:`, `instances:`) and scalar values
    (`max_price_per_hour: 1.0`). Scalars are auto-coerced to int/float when
    they look numeric, otherwise kept as strings.

    Avoids a PyYAML dependency since the format is predictable.
    """
    data: dict[str, dict] = {}
    group: Optional[str] = None
    current_list: Optional[list[str]] = None

    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            group = line[:-1].strip()
            data[group] = {}
            current_list = None
        elif line.startswith("    ") and line.endswith(":"):
            assert group is not None, f"List key {line!r} before any group"
            key = stripped[:-1]
            data[group][key] = []
            current_list = data[group][key]
        elif (line.startswith("    ") and ":" in stripped
              and not stripped.startswith("- ")
              and not stripped.endswith(":")):
            # Scalar key: value (e.g. 'max_price_per_hour: 1.0').
            assert group is not None, f"Scalar key {line!r} before any group"
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Coerce numeric-looking values; keep strings as-is otherwise.
            parsed: object
            try:
                parsed = int(value) if value.lstrip("-").isdigit() else float(value)
            except ValueError:
                parsed = value
            data[group][key] = parsed
            current_list = None
        elif stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip())
    return data


# ---------------------------------------------------------------------------
# runpodctl subprocess wrappers
# ---------------------------------------------------------------------------


def runpodctl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = ["runpodctl", *args]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        log("runpodctl not found in PATH. Install it first.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="", stderr="timeout"
        )


def runpodctl_json(*args: str, timeout: int = 60):
    proc = runpodctl(*args, "-o", "json", timeout=timeout)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def discover_gpu_id_map() -> dict[str, str]:
    """Build {displayName: gpuId} from `runpodctl gpu list`."""
    data = runpodctl_json(
        "gpu", "list", "--include-unavailable", timeout=30
    )
    if not isinstance(data, list):
        return {}
    return {
        item["displayName"]: item["gpuId"]
        for item in data
        if item.get("displayName") and item.get("gpuId")
    }


# GPU catalog with pricing — populated at startup via GraphQL since
# `runpodctl gpu list` does NOT include price fields. Used for budget-based
# instance selection (manifest's `max_price_per_hour`). Empty list if API
# unreachable; in that case budget filters silently no-op and the script
# falls back to whatever's in the manifest's explicit `instances:` list.
GPU_CATALOG: list[dict] = []


def _load_runpod_api_key() -> Optional[str]:
    """Read the API key out of ~/.runpod/config.toml. We avoid a tomli
    dependency by regex'ing the file — the CLI always writes the key on a
    single line like `apikey = '...'`. Also honours RUNPOD_API_KEY env var
    so CI / containerized runs can inject it without touching the file."""
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


def discover_gpu_catalog() -> list[dict]:
    """Fetch GPU types + per-hour prices from RunPod GraphQL.

    Each entry has: id, displayName, memoryInGb, securePrice, communityPrice,
    manufacturer. Returns [] on any failure (script will still work if the
    manifest uses explicit `instances:` lists)."""
    api_key = _load_runpod_api_key()
    if not api_key:
        return []
    query = ("{ gpuTypes { id displayName memoryInGb "
             "securePrice communityPrice manufacturer } }")
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        "https://api.runpod.io/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # api.runpod.io is fronted by Cloudflare, which rejects the default
            # Python-urllib User-Agent with error code 1010. Identify as a
            # generic client to get through.
            "User-Agent": "test-images.py/1.0 (+runpod-smoketest)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        log(f"warn: could not fetch GPU prices: {exc}")
        return []
    return ((payload.get("data") or {}).get("gpuTypes") or [])


def resolve_instances(group_name: str, group_config: dict) -> list[str]:
    """Decide which GPU display names this group should try, in order.

    Priority:
      1. Explicit `instances:` list in the manifest — wins, used as-is.
      2. `max_price_per_hour: X` (+ optional `min_vram_gb`, `manufacturer`)
         — auto-pick from RunPod catalog, sorted cheapest first.

    Returns [] when neither is set (caller will SKIP the group).
    """
    explicit = group_config.get("instances") or []
    if explicit:
        return list(explicit)

    max_price = group_config.get("max_price_per_hour")
    if max_price is None:
        return []

    if not GPU_CATALOG:
        log(
            f"warn: group '{group_name}' uses max_price_per_hour but the "
            "GPU catalog (with prices) is empty — set RUNPOD_API_KEY or use "
            "an explicit instances: list",
        )
        return []

    min_vram = group_config.get("min_vram_gb", 0)
    manufacturer = (group_config.get("manufacturer") or "").lower()
    price_field = (
        "communityPrice" if CLOUD_TYPE.upper() == "COMMUNITY" else "securePrice"
    )

    candidates: list[tuple[float, str]] = []
    for gpu in GPU_CATALOG:
        price = gpu.get(price_field) or 0
        # price=0 in catalog usually means "not offered in this cloud type" —
        # skip rather than mistakenly treat as free.
        if price <= 0 or price > float(max_price):
            continue
        if gpu.get("memoryInGb", 0) < int(min_vram):
            continue
        if manufacturer and (gpu.get("manufacturer") or "").lower() != manufacturer:
            continue
        name = gpu.get("displayName")
        if name:
            candidates.append((float(price), name))

    candidates.sort(key=lambda x: x[0])
    return [name for _, name in candidates]


def discover_registry_auth(prefer_name: str = "") -> Optional[str]:
    """Find a registry auth id from `runpodctl registry list`."""
    data = runpodctl_json("registry", "list", timeout=30)
    if not isinstance(data, list) or not data:
        return None
    if prefer_name:
        for item in data:
            if (item.get("name") or "").lower() == prefer_name.lower():
                return item.get("id") or item.get("registryAuthId")
    first = data[0]
    return first.get("id") or first.get("registryAuthId")


# ---------------------------------------------------------------------------
# Pod lifecycle
# ---------------------------------------------------------------------------

# Set of pod IDs that are currently alive across all workers. Used by signal
# handlers / atexit to ensure NOTHING leaks when the script dies. Guarded by
# a lock so parallel workers can register/deregister safely.
ACTIVE_POD_IDS: set[str] = set()
_active_pods_lock = threading.Lock()


def register_pod(pod_id: str) -> None:
    with _active_pods_lock:
        ACTIVE_POD_IDS.add(pod_id)


def unregister_pod(pod_id: str) -> None:
    with _active_pods_lock:
        ACTIVE_POD_IDS.discard(pod_id)


def cleanup_pod(pod_id: str) -> None:
    """Delete a single pod and unregister it from the tracking set."""
    if not pod_id:
        return
    log(f"Cleaning up pod {pod_id}...")
    runpodctl("pod", "delete", pod_id, timeout=30)
    unregister_pod(pod_id)


def cleanup_all() -> None:
    """Delete every pod still tracked as active. Used at exit / on signal."""
    with _active_pods_lock:
        leftover = list(ACTIVE_POD_IDS)
    if not leftover:
        return
    log(f"Cleaning up {len(leftover)} leftover pod(s)...")
    for pid in leftover:
        try:
            runpodctl("pod", "delete", pid, timeout=30)
        except Exception as exc:  # noqa: BLE001
            log(f"  failed to delete {pid}: {exc}")
        unregister_pod(pid)


atexit.register(cleanup_all)


def _signal_handler(signum: int, _frame) -> None:
    log(f"Caught signal {signum}, cleaning up...")
    cleanup_all()
    sys.exit(130)


for _sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(_sig, _signal_handler)


def _extract_error(raw: str) -> str:
    """Pull a concise error string out of runpodctl's noisy create-failure output
    (which usually dumps the JSON error followed by a full `--help` listing)."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{") and '"error"' in line:
            try:
                return json.loads(line).get("error", line)
            except json.JSONDecodeError:
                return line
        if line and line.split()[0] in {"Usage:", "Flags:", "Aliases:",
                                         "Examples:", "Global"}:
            break
        if line:
            return line
    return raw[:200]


def create_pod(image: str, gpu_id: str, name: str) -> tuple[Optional[str], str]:
    args = [
        "pod", "create",
        "--image", image,
        "--gpu-id", gpu_id,
        "--gpu-count", "1",
        "--cloud-type", CLOUD_TYPE,
        "--container-disk-in-gb", str(DISK_GB),
        "--ports", "22/tcp",
        "--name", name,
        "--terminate-after", AUTO_TERMINATE,
        "-o", "json",
    ]
    if REGISTRY_AUTH_ID:
        args.extend(["--registry-auth-id", REGISTRY_AUTH_ID])
    # Constrain scheduling to hosts whose driver supports this image's CUDA.
    # Without this, RunPod may land a cu13.0 image on an older-driver host and
    # the container fails at startup with `nvidia-container-cli: cuda>=13.0`.
    cuda_version = detect_cuda_version(image)
    if cuda_version:
        args.extend(["--min-cuda-version", cuda_version])
    proc = runpodctl(*args, timeout=120)
    raw = (proc.stderr + proc.stdout).strip()
    if proc.returncode != 0:
        return None, _extract_error(raw)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, _extract_error(raw)
    pod_id = data.get("id") or (data.get("pod") or {}).get("id")
    return pod_id, raw


RUNTIME_ERROR_RE = re.compile(
    r"toomanyrequests"
    r"|rate\s+limit"
    r"|failed\s+to\s+pull\s+image"
    r"|error\s+creating\s+container"
    r"|manifest\s+(?:unknown|not\s+found)"
    r"|access\s+denied"
    r"|no\s+such\s+image",
    re.IGNORECASE,
)


def pod_state(pod_id: str) -> dict:
    """Return the relevant subset of pod state for decision-making.

    When the pod is created with `--ports 22/tcp` (which we do), `pod get`
    populates a useful `ssh` block with `ip`, `port`, and `ssh_key.in_account`
    once the pod is scheduled. We use these as the real readiness signal.
    """
    data = runpodctl_json("pod", "get", pod_id, timeout=30)
    if not isinstance(data, dict):
        return {}
    ssh = data.get("ssh") or {}
    return {
        "desired": data.get("desiredStatus"),
        "uptime": data.get("uptimeSeconds") or 0,
        "ssh_ip": ssh.get("ip") or "",
        "ssh_port": ssh.get("port") or 0,
        "ssh_error": ssh.get("error") or "",
        "ssh_key_in_account": (ssh.get("ssh_key") or {}).get("in_account"),
        "last_status_change": data.get("lastStatusChange"),
        "raw": data,
    }


def pod_status(pod_id: str) -> Optional[str]:
    """Returns `desiredStatus` — note this is always RUNNING after creation
    so it can ONLY be used to detect terminal states (EXITED/FAILED/DEAD)."""
    return pod_state(pod_id).get("desired")


def pod_runtime_error(pod_id: str) -> Optional[str]:
    """Inspect pod-get response for container-runtime errors (pull failures,
    bad images, etc.) that appear *before* the pod ever reaches RUNNING.
    Returns a short error string or None."""
    data = runpodctl_json("pod", "get", pod_id, timeout=30)
    if not isinstance(data, dict):
        return None
    # Collect candidate error/event strings from several plausible fields.
    candidates: list[str] = []
    for key in ("lastError", "errorMessage", "statusMessage", "lastStatusChange"):
        val = data.get(key)
        if isinstance(val, str) and val:
            candidates.append(val)
    runtime = data.get("runtime") or {}
    for key in ("lastError", "errorMessage", "statusMessage"):
        val = runtime.get(key)
        if isinstance(val, str) and val:
            candidates.append(val)
    for events_field in ("events", "statusEvents", "containerEvents"):
        events = data.get(events_field) or runtime.get(events_field)
        if isinstance(events, list):
            for ev in events:
                msg = ev.get("message") if isinstance(ev, dict) else str(ev)
                if isinstance(msg, str) and msg:
                    candidates.append(msg)
    # Also scan container logs — pull errors sometimes only land there.
    for key in ("containerLogs", "logs"):
        val = data.get(key) or runtime.get(key)
        if isinstance(val, str):
            candidates.extend(val.splitlines())
    for line in candidates:
        if RUNTIME_ERROR_RE.search(line):
            return line.strip()[:300]
    return None


def _resolve_ssh_identity() -> Optional[str]:
    """Find the SSH private key to use for the runpodctl-managed PUBLIC_KEY.

    Order of preference:
      1. RUNPOD_SSH_KEY env var (explicit override)
      2. runpodctl-managed key at ~/.runpod/ssh/runpodctl-ssh-key
      3. Standard ssh defaults (~/.ssh/id_ed25519, ~/.ssh/id_rsa, ssh-agent)
    Returns the path if a non-default key was found, else None (let ssh
    pick a default from its standard search path / ssh-agent)."""
    if SSH_IDENTITY:
        return SSH_IDENTITY if os.path.isfile(SSH_IDENTITY) else None
    for candidate in (
        "~/.runpod/ssh/runpodctl-ssh-key",
        "~/.runpod/runpodctl-ssh-key",
        "~/.ssh/runpodctl-ssh-key",
    ):
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


def _ssh_command_prefix(host: str, port: int) -> list[str]:
    """Build the `ssh ... root@<host> -p <port>` prefix common to all SSH calls."""
    cmd = ["ssh", *SSH_OPTS, "-p", str(port)]
    identity = _resolve_ssh_identity()
    if identity:
        cmd.extend(["-i", identity])
    cmd.append(f"root@{host}")
    return cmd


def ssh_probe(host: str, port: int, timeout: int = 8) -> tuple[bool, str]:
    """One-shot SSH connection attempt. Returns (success, stderr_excerpt).
    Used as the real container-readiness signal."""
    cmd = [*_ssh_command_prefix(host, port), "echo", "ready"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "ssh probe timed out"
    except FileNotFoundError:
        return False, "ssh binary not found"
    if r.returncode == 0 and "ready" in r.stdout:
        return True, ""
    return False, (r.stderr or r.stdout).strip()[:200]


def cuda_check_command(group: str) -> str:
    """Return a one-line shell command that functionally validates the GPU/CUDA
    stack for a given image group. Returns empty string for groups where no
    GPU check applies (e.g. CPU-only base images).

    The command MUST exit non-zero on failure so the SSH call can detect it.
    Output goes to stdout/stderr and is captured for the report."""
    if group == "base_cpu":
        return ""

    if group in ("pytorch", "nvidia-pytorch", "rocm"):
        # Test that PyTorch actually sees the GPU through CUDA/ROCm. This catches
        # mismatched driver/toolkit versions, missing libs, broken Python envs.
        return (
            "python3 - <<'PY'\n"
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

    if group == "base_gpu":
        # No PyTorch in base images — just verify the CUDA toolkit is installed
        # and the driver responds to a real query (more than just nvidia-smi banner).
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

    return ""


def run_cuda_check(host: str, port: int, group: str) -> tuple[bool, str]:
    """Run the GPU/CUDA functional check inside the pod over SSH.
    Returns (ok, output). ok=True when:
      * the group has no check defined (treated as pass), OR
      * the remote command exits 0.
    output contains stdout+stderr for inclusion in the run log."""
    cmd = cuda_check_command(group)
    if not cmd:
        return True, "(no GPU check for this group)"
    ssh_cmd = [*_ssh_command_prefix(host, port), cmd]
    try:
        r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "cuda check timed out after 60s"
    except FileNotFoundError:
        return False, "ssh binary not found"
    combined = (r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


def fetch_logs_via_ssh(host: str, port: int, tail: int = 20) -> Optional[str]:
    """SSH to the pod and grab the most useful diagnostic info from inside
    the container. Returns stdout on success, None if SSH didn't work."""
    if not SSH_LOG_FETCH:
        return None
    remote_cmd = (
        "set +e; "
        "echo '=== uname / hostname ==='; uname -a; hostname; "
        f"echo '=== last {tail} /var/log/syslog lines ==='; "
        f"tail -n {tail} /var/log/syslog 2>/dev/null || echo '(no /var/log/syslog)'; "
        f"echo '=== last {tail} dmesg lines ==='; "
        f"dmesg --no-pager 2>/dev/null | tail -n {tail} || echo '(dmesg unavailable)'; "
        "echo '=== /var/log/*.log tails ==='; "
        "for f in /var/log/*.log; do "
        "  [ -f \"$f\" ] || continue; "
        "  echo \"--- $f ---\"; tail -n 5 \"$f\" 2>/dev/null; "
        "done; "
        "echo '=== nvidia-smi ==='; nvidia-smi 2>&1 | head -n 15 || echo '(no nvidia-smi)'"
    )
    cmd = [*_ssh_command_prefix(host, port), remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout
    return f"__SSH_FAILED__\nreturncode={r.returncode}\nstderr: {r.stderr.strip()[:400]}"


def dump_pod_logs(pod_id: str, tail: int = 20) -> None:
    """Print pod metadata + container logs (via direct SSH) before terminating."""
    data = runpodctl_json("pod", "get", pod_id, timeout=30)
    if not isinstance(data, dict):
        log("(could not fetch pod state)", indent=2)
        return
    ssh = data.get("ssh") or {}
    host, port = ssh.get("ip"), ssh.get("port")

    log(f"--- pod metadata for {pod_id} ---", indent=2)
    for key, val in [
        ("desiredStatus",    data.get("desiredStatus")),
        ("uptimeSeconds",    data.get("uptimeSeconds")),
        ("ssh.ip:port",      f"{host}:{port}" if host and port else None),
        ("ssh.error",        ssh.get("error")),
        ("ssh.key_in_account", (ssh.get("ssh_key") or {}).get("in_account")),
        ("imageName",        data.get("imageName")),
        ("lastStatusChange", data.get("lastStatusChange")),
    ]:
        log(f"  {key:20s} = {val!r}", indent=2)

    if not (host and port):
        log("  (no SSH endpoint yet — skipping log fetch)", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return

    log(f"--- container/system logs via SSH (root@{host}:{port}) ---", indent=2)
    logs = fetch_logs_via_ssh(host, int(port), tail=tail)
    if logs is None:
        log("  (SSH log fetch disabled or ssh binary not found)", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return
    if logs.startswith("__SSH_FAILED__"):
        log("  SSH could not reach the pod:", indent=2)
        for line in logs.splitlines()[1:]:
            log(f"    {line}", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return
    for line in logs.splitlines():
        log(f"  {line}", indent=2)


def wait_for_running(pod_id: str) -> tuple[str, str]:
    """Returns (outcome, detail). Outcome is one of:
        'RUNNING'   SSH probe to root@<ssh.ip>:<ssh.port> succeeded — the
                    container's sshd is up, which means the container has fully
                    booted and we can trust it as healthy.
        'TERMINAL'  desiredStatus flipped to EXITED/FAILED/DEAD/TERMINATED.
        'TIMEOUT'   SSH never reachable within CREATE_TIMEOUT — pod stuck
                    initializing (capacity issue or image broken).

    SSH probing is the real health-check now. We poll `pod get` to discover
    ssh.ip / ssh.port (assigned by RunPod once a machine is allocated), then
    try `ssh root@ip -p port 'echo ready'` until it succeeds. This works
    because:
      * `--ports 22/tcp` in pod create makes RunPod NAT a public port to the
        container's 22, so the container's sshd is reachable from anywhere.
      * The PUBLIC_KEY env we inject lands in /root/.ssh/authorized_keys.
      * A successful SSH means the container booted + sshd started — the
        canonical signal of readiness, much stronger than `desiredStatus`
        (always RUNNING) or `uptimeSeconds` (stale in this CLI version).
    """
    start = time.time()
    deadline = start + CREATE_TIMEOUT
    last_summary: Optional[tuple] = None
    ssh_attempts = 0
    stall_hinted = False  # one-time hint when pod has no ssh endpoint for a while

    while time.time() < deadline:
        st = pod_state(pod_id)
        if not st:
            time.sleep(POLL_INTERVAL)
            continue

        desired = st.get("desired")
        uptime = st.get("uptime") or 0
        host = st.get("ssh_ip") or ""
        port = st.get("ssh_port") or 0
        elapsed = int(time.time() - start)

        if desired in ("EXITED", "FAILED", "DEAD", "TERMINATED"):
            return "TERMINAL", f"pod entered {desired} after {elapsed}s"

        if host and port:
            ssh_attempts += 1
            ok, err = ssh_probe(host, int(port), timeout=8)
            summary = (desired, host, port, ok)
            if summary != last_summary:
                log(
                    f"t+{elapsed}s endpoint=root@{host}:{port} "
                    f"ssh_probe={'OK' if ok else 'FAIL'} (#{ssh_attempts})"
                    + (f" — {err}" if not ok and err else ""),
                    indent=2,
                )
                last_summary = summary
            if ok:
                return "RUNNING", (
                    f"ssh probe succeeded after {elapsed}s "
                    f"({ssh_attempts} attempts, endpoint root@{host}:{port})"
                )
        else:
            summary = (desired, host, port, False)
            if summary != last_summary:
                log(
                    f"t+{elapsed}s desired={desired!r} uptime={uptime}s "
                    "ssh endpoint not assigned yet",
                    indent=2,
                )
                last_summary = summary
            # Surface a hint after STALL_HINT_AFTER seconds without an SSH
            # endpoint. RunPod doesn't expose pull progress via API/CLI, so
            # this is the best we can do — point the user at the UI and at
            # the most common cause (slow/throttled image pull).
            if elapsed >= STALL_HINT_AFTER and not stall_hinted:
                log(
                    f"pod still has no SSH endpoint after {elapsed}s. "
                    "Most common cause is a slow or throttled image pull. "
                    "Check the UI for pull progress: "
                    f"https://www.runpod.io/console/pods/{pod_id}",
                    indent=2,
                )
                log(
                    "If you see 'toomanyrequests' in the UI logs, you've hit "
                    "the Docker Hub pull rate limit — wait 6h, log in to a "
                    "paid Docker Hub account, or reduce MAX_PARALLEL.",
                    indent=2,
                )
                stall_hinted = True

        time.sleep(POLL_INTERVAL)

    return "TIMEOUT", (
        f"SSH endpoint never became reachable in {CREATE_TIMEOUT}s "
        f"({ssh_attempts} probes) — pod stuck initializing. Likely causes: "
        "(1) slow/throttled image pull (check UI for pull progress), "
        "(2) Docker Hub rate limit if many parallel pulls of the same image, "
        "(3) host scheduling delay on a saturated DC"
    )


# ---------------------------------------------------------------------------
# Test logic
# ---------------------------------------------------------------------------


def test_pair(image: str, instance: str, group: str) -> str:
    """Returns one of:
        'PASS'         — image booted, CUDA check OK, survived dwell
        'FAIL'         — image really is broken (container crashed, CUDA failed,
                         pod entered terminal state) — moving to another GPU
                         won't help, the image itself is the problem
        'UNAVAILABLE'  — RunPod has no capacity for this instance — try next
        'STUCK'        — pod was created but RunPod never assigned an SSH
                         endpoint within CREATE_TIMEOUT. Almost always a bad
                         host in the scheduler pool, not an image bug — caller
                         should try a different instance type.

    `group` is the manifest section name (e.g. 'pytorch', 'base_gpu') and is
    used to select the appropriate GPU/CUDA functional check."""
    gpu_id = resolve_gpu_id(instance)
    cuda = detect_cuda_version(image)
    cuda_note = f", min-cuda={cuda}" if cuda else ""
    log(
        f"attempt: instance='{instance}' (--gpu-id '{gpu_id}'){cuda_note}",
        indent=1,
    )

    # Retry on transient orchestrator errors (5xx, "something went wrong",
    # 502/503/504). These often happen when several workers race for the same
    # scarce GPU at the same instant. We back off and retry a few times before
    # giving up and moving on to the next instance.
    pod_id: Optional[str] = None
    raw = ""
    for attempt in range(1, CREATE_RETRIES + 1):
        # New name on each attempt — RunPod may keep a server-side record of
        # rejected names briefly, and unique names also make logs unambiguous.
        name = (
            f"smoketest-{int(time.time())}-"
            f"{threading.get_ident() % 10000:04d}-{attempt}"
        )
        pod_id, raw = create_pod(image, gpu_id, name)
        if pod_id:
            break
        if UNAVAILABLE_RE.search(raw):
            log(f"instance unavailable, will try next ({raw[:120]})", indent=2)
            return "UNAVAILABLE"
        if TRANSIENT_RE.search(raw) and attempt < CREATE_RETRIES:
            backoff = CREATE_RETRY_BACKOFF * attempt
            log(
                f"transient pod-create error ({raw[:120]}), "
                f"retry {attempt}/{CREATE_RETRIES - 1} in {backoff}s",
                indent=2,
            )
            time.sleep(backoff)
            continue
        log(f"pod create failed: {raw[:400]}", indent=2)
        return "FAIL"

    if not pod_id:
        log(f"pod create failed after {CREATE_RETRIES} attempts: {raw[:200]}",
            indent=2)
        return "FAIL"

    register_pod(pod_id)
    log(
        f"pod {pod_id} created, waiting for RUNNING (timeout {CREATE_TIMEOUT}s)",
        indent=2,
    )

    try:
        state, detail = wait_for_running(pod_id)
        if state != "RUNNING":
            # Distinguish "host never came up" (STUCK — try another instance)
            # from "container actually died" (FAIL — image is broken).
            # TIMEOUT with no SSH endpoint ever assigned is almost always a
            # scheduler/host issue, not the image: a different GPU type lands
            # on a different host pool and usually works.
            st = pod_state(pod_id)
            ever_had_ssh = bool(st.get("ssh_ip") and st.get("ssh_port"))
            if state == "TIMEOUT" and not ever_had_ssh:
                log(
                    f"{state.lower()} -- {detail} -- STUCK (no SSH endpoint "
                    "was ever assigned; trying next instance type)",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "STUCK"
            log(f"{state.lower()} -- {detail} -- FAIL", indent=2)
            dump_pod_logs(pod_id)
            return "FAIL"

        log(f"smoke check passed: {detail}", indent=2)

        # Run the per-group CUDA/GPU functional check. This is the real
        # "does this image actually work" gate — distinct from "did it boot".
        st = pod_state(pod_id)
        host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
        if host and port and cuda_check_command(group):
            log(f"running GPU/CUDA functional check for group '{group}'...", indent=2)
            ok, output = run_cuda_check(host, int(port), group)
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log("cuda check FAILED -- image broken", indent=2)
                dump_pod_logs(pod_id)
                return "FAIL"
            log("cuda check passed", indent=2)

        # Brief dwell to catch containers that boot, accept SSH, then crash.
        # Most real images hit this in the first ~30s if they're going to crash.
        if DWELL_SEC > 0:
            log(f"dwelling {DWELL_SEC}s and re-probing SSH...", indent=2)
            time.sleep(DWELL_SEC)
            st = pod_state(pod_id)
            host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
            if host and port:
                ok, err = ssh_probe(host, int(port), timeout=8)
                if not ok:
                    log(
                        f"ssh probe failed after dwell ({err}) -- "
                        "container crashed -- FAIL",
                        indent=2,
                    )
                    dump_pod_logs(pod_id)
                    return "FAIL"

        dump_pod_logs(pod_id)
        return "PASS"
    finally:
        # Always clean up this specific pod, even on exception.
        cleanup_pod(pod_id)


def test_image(image: str, instances: list[str], group: str) -> tuple[str, str]:
    """Returns (status, note).

    Iterates instance types until one PASSes. Stops early on FAIL (real image
    bug — no point trying another GPU). UNAVAILABLE (capacity) and STUCK
    (RunPod gave us a dead host) just move on to the next instance.
    """
    log(f"image: {image}")
    stuck_instances: list[str] = []
    for inst in instances:
        result = test_pair(image, inst, group)
        if result == "PASS":
            return "PASS", ""
        if result == "FAIL":
            return "FAIL", "container did not stay healthy"
        if result == "STUCK":
            stuck_instances.append(inst)
    if stuck_instances:
        # We tried every instance and RunPod never gave us a working host on
        # any of them — surface that distinctly from "no capacity at all".
        log(
            f"all {len(instances)} instances either unavailable or stuck "
            f"(stuck: {stuck_instances})",
            indent=1,
        )
        return "SKIP", (
            f"RunPod never assigned an SSH endpoint on {len(stuck_instances)} "
            "instance type(s) — likely a scheduler issue, try again later"
        )
    log("all instances exhausted, none available", indent=1)
    return "SKIP", "no listed instances available"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    images_path = Path(sys.argv[1] if len(sys.argv) > 1 else "images")
    group_filter = sys.argv[2] if len(sys.argv) > 2 else None

    if not images_path.is_file():
        log(f"Images manifest not found: {images_path}")
        return 1

    auth = runpodctl("user", timeout=15)
    if auth.returncode != 0:
        log("runpodctl is not authenticated. Run 'runpodctl doctor'.")
        return 1

    GPU_ID_MAP.update(discover_gpu_id_map())
    log(f"discovered {len(GPU_ID_MAP)} GPU types from runpodctl")

    GPU_CATALOG.extend(discover_gpu_catalog())
    if GPU_CATALOG:
        log(
            f"loaded GPU pricing for {len(GPU_CATALOG)} types "
            "(GraphQL: gpuTypes)"
        )
    else:
        log(
            "warn: no GPU pricing data — budget-based instance selection "
            "(max_price_per_hour) will be disabled. Set RUNPOD_API_KEY or "
            "ensure ~/.runpod/config.toml has 'apikey'."
        )

    global REGISTRY_AUTH_ID
    if not REGISTRY_AUTH_ID:
        REGISTRY_AUTH_ID = discover_registry_auth(REGISTRY_AUTH_NAME) or ""
    if REGISTRY_AUTH_ID:
        log(f"using registry auth: {REGISTRY_AUTH_ID}")
    else:
        log(
            "warn: no registry auth configured — Docker Hub pulls will be "
            "anonymous and likely hit the toomanyrequests rate limit"
        )

    manifest = parse_manifest(images_path)

    # Resolve the instances list for each non-CPU group now (so we can warn
    # about typos / empty lists once, up front, instead of per-job). For
    # explicit-list groups this is just a copy. For budget-based groups this
    # queries the GPU_CATALOG and picks cheapest-first.
    resolved_instances: dict[str, list[str]] = {}
    for grp, contents in manifest.items():
        if grp == "base_cpu":
            continue
        resolved_instances[grp] = resolve_instances(grp, contents)

    # Warn about explicit-list entries that don't match any known GPU display
    # name — these would be passed to runpodctl verbatim and fail.
    unmapped = sorted({
        inst
        for grp, instances in resolved_instances.items()
        for inst in instances
        if not is_known_gpu(inst)
    })
    if unmapped:
        log(
            f"warn: {len(unmapped)} instance(s) don't match any RunPod "
            "displayName — check spelling/casing:"
        )
        for inst in unmapped:
            log(f"  - {inst!r}", indent=1)

    # Log the resolved instance list per group — especially useful when the
    # user wrote `max_price_per_hour: X` and wants to see what was picked.
    for grp, instances in resolved_instances.items():
        contents = manifest[grp]
        if "max_price_per_hour" in contents and not contents.get("instances"):
            budget = contents["max_price_per_hour"]
            preview = ", ".join(instances[:8]) + (
                f", ... (+{len(instances) - 8} more)" if len(instances) > 8 else ""
            )
            log(
                f"group '{grp}': budget ≤ ${budget}/hr → {len(instances)} "
                f"candidate(s): {preview or '(none — no GPU fits)'}"
            )

    results: dict[str, tuple[str, str]] = {}

    # Flatten the manifest into a list of (image, group, instances) jobs that
    # can run independently. Skip groups we can't actually exercise.
    jobs: list[tuple[str, str, list[str]]] = []
    for group, contents in manifest.items():
        if group_filter and group != group_filter:
            continue
        if group == "base_cpu":
            log(
                f"skipping CPU group '{group}' (CPU flavor selection "
                "not supported in runpodctl 2.3.0)"
            )
            for img in contents.get("images", []):
                results[img] = ("SKIP", "CPU flavor unsupported in runpodctl")
            continue
        instances = resolved_instances.get(group, [])
        if not instances:
            log(
                f"skipping group '{group}': no instances resolved "
                "(neither 'instances:' nor 'max_price_per_hour:' produced "
                "any candidates)"
            )
            for img in contents.get("images", []):
                results[img] = ("SKIP", "no instances configured")
            continue
        for img in contents.get("images", []):
            jobs.append((img, group, instances))

    if not jobs:
        log("no jobs to run after filtering")
    else:
        print()
        log(
            f"==================== running {len(jobs)} job(s) "
            f"with MAX_PARALLEL={MAX_PARALLEL} ===================="
        )

        if MAX_PARALLEL <= 1:
            # Serial mode — simpler logs, no worker tags.
            current_group = None
            for img, group, instances in jobs:
                if group != current_group:
                    print()
                    log(f"---------- group: {group} ----------")
                    current_group = group
                results[img] = test_image(img, instances, group)
        else:
            # Parallel mode — tag each pool thread so output is readable when
            # multiple pods are progressing at the same time. The tag is
            # assigned to the thread (not the job), so e.g. with 5 jobs and
            # 3 workers you still see only W1/W2/W3, each handling 1-2 jobs.
            def _run_job(img: str, grp: str, insts: list[str]):
                ensure_worker_tag()
                log(f"start [group={grp}] image={img}")
                res = test_image(img, insts, grp)
                log(f"done  [group={grp}] image={img} -> {res[0]}")
                return img, res

            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
                futures = [
                    pool.submit(_run_job, img, grp, insts)
                    for img, grp, insts in jobs
                ]
                for fut in as_completed(futures):
                    img, res = fut.result()
                    results[img] = res

    # ----- Summary -----
    print()
    print("=" * 84)
    print(" SUMMARY ".center(84, "="))
    print("=" * 84)
    counts: dict[str, int] = defaultdict(int)
    for status, _ in results.values():
        counts[status] += 1
    print(
        f"totals: {counts['PASS']} PASS, "
        f"{counts['FAIL']} FAIL, "
        f"{counts['SKIP']} SKIP\n"
    )
    for want in ("FAIL", "SKIP", "PASS"):
        for img, (status, note) in results.items():
            if status != want:
                continue
            note_str = f" -- {note}" if note else ""
            print(f"  {want:6s} {img}{note_str}")

    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
