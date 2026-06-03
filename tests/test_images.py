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
                           (one of `instances:` or `max_price_per_hour:` required
                            — except for the `base_cpu` group, see below)
    max_price_per_hour:    USD/hr budget — auto-pick any GPU at this price or
                           below, cheapest first. Loses to explicit `instances:`
                           if both are set.
    min_vram_gb:           extra filter for budget mode (default 0)
    manufacturer:          'Nvidia' or 'AMD' filter for budget mode (default any)
    exclude_instances:     list of fnmatch-style patterns (case-insensitive)
                           subtracted from the candidate list AFTER `instances:`
                           or budget selection. Use to block known-bad host
                           pairings without rewriting the whole list, e.g.
                               exclude_instances:
                               - "*Blackwell*"
                           skips every Blackwell GPU (sm_100/sm_120 are not in
                           the kernel set of PyTorch ≤ 2.6 wheels).
    min_cuda_version:      'X.Y' string passed to `runpodctl pod create
                           --min-cuda-version`. Only used as a FALLBACK when
                           the image tag itself doesn't encode a CUDA version
                           (e.g. NGC `nvidia-pytorch:25.11`). Image tags like
                           `cu1281` / `cuda1281` always win.
    test_jupyter:          true | false — when true, the pod is created with
                           JUPYTER_PASSWORD=admin in env and HTTP port 8888
                           exposed, then the script SSHes in and verifies
                           Jupyter Lab is actually listening. Use for groups
                           whose images use container-template/start.sh
                           (runpod/base, runpod/pytorch, runpod/autoresearch,
                           rocm). Skip for NGC nvidia-pytorch (different
                           entrypoint).            (default: false)

The `base_cpu` group is special: runpodctl 2.3.0 does not let us pick a
specific CPU flavor (--gpu-id is rejected for --compute-type CPU), so the
manifest needs ONLY an `images:` list for that group — no `instances:` /
`max_price_per_hour:` / `min_vram_gb:`. RunPod picks a CPU flavor for us.

Env vars (overridable):
    CLOUD_TYPE       SECURE | COMMUNITY                       (default: SECURE)
    DISK_GB          container disk size for GPU pods         (default: 100)
    CPU_DISK_GB      container disk size for CPU pods. RunPod caps this per
                     CPU flavor (20 GB on the cheapest, 30 GB on larger ones);
                     20 is the universal safe value           (default: 20)
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

Functional check (runs over SSH after the container is reachable). The check
is selected by inspecting the image REF, not the manifest group name — so
new groups don't silently skip the check:
    image has 'pytorch' / 'torch\\d' in ref
        -> torch.cuda.is_available + matmul on device (catches broken
           drivers, missing libs, mismatched toolkit/driver versions).
    image has 'cuda' / 'cu\\d' / 'rocm' (but no torch markers)
        -> nvidia-smi -L + driver/memory query + nvcc --version. Covers
           base GPU images and autoresearch (whose torch is in a venv
           not reachable from the system python we ssh into).
    otherwise (no GPU markers)
        -> no check. Pod must still boot and survive DWELL_SEC.

Jupyter check (opt-in via manifest `test_jupyter: true`). Two stages,
both must pass:
    1. In-pod: SSH into the pod and curl http://127.0.0.1:8888/api/status
       with our token. Catches silent start.sh failures (e.g.
       `python3 -m jupyter` not finding the module on Ubuntu 22.04 — the
       kind of bug that prints "Jupyter Lab started" in the container log
       while no server is actually running).
    2. Public proxy: from the test machine, GET
       https://<pod-id>-8888.proxy.runpod.net/api/status with the token.
       Catches port-type misconfigurations (`8888/tcp` instead of
       `8888/http` — proxy never wires up non-http ports) and DNS/proxy
       registration issues that would prevent real users from reaching
       Jupyter from the RunPod console.

Jupyter env vars:
    JUPYTER_WAIT_TIMEOUT   seconds the in-pod probe waits for :8888 to bind
                                                              (default: 30)
    JUPYTER_PROXY_TIMEOUT  seconds the proxy probe retries while RunPod's
                           ingress registers the new pod (default: 60)
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
# CPU pods on RunPod cap container disk by flavor: the cheapest flavors
# (cpu3c-2-4 and similar) reject >20 GB outright; larger ones cap at 30 GB.
# 20 GB is the universal safe value — and plenty for a smoke-test that
# only boots start.sh and dwells for a minute. Overridable for the rare
# case where a CPU image actually needs more.
CPU_DISK_GB = int(os.environ.get("CPU_DISK_GB", "20"))
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


_TRUE_RE = re.compile(r"^(true|yes|on|1)$", re.IGNORECASE)
_FALSE_RE = re.compile(r"^(false|no|off|0)$", re.IGNORECASE)


def _normalize_bool(value: object) -> Optional[bool]:
    """Coerce a manifest scalar to bool. Returns None when the value isn't
    obviously truthy/falsy so callers can distinguish "absent" from "false"."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().strip('"').strip("'")
    if _TRUE_RE.match(s):
        return True
    if _FALSE_RE.match(s):
        return False
    return None


def _normalize_cuda_version(value: object) -> Optional[str]:
    """Coerce a manifest `min_cuda_version` value to the 'X.Y' string format
    that `runpodctl --min-cuda-version` expects.

    Accepts ints (`13` → '13.0'), floats (`12.8` → '12.8', `13.0` → '13.0'),
    and strings (with or without surrounding quotes). Returns None for
    empty/None inputs so callers can `value or fallback`-chain.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value}.0"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value)}.0"
        return f"{value:g}"
    return str(value).strip().strip('"').strip("'") or None


# Per-group fallback CUDA version, populated in main() from
# `min_cuda_version:` manifest fields. Looked up by `create_pod` only when
# `detect_cuda_version(image)` returns None (i.e. image tag has no embedded
# CUDA — NGC `nvidia-pytorch:25.11` and similar opaque tags).
GROUP_MIN_CUDA: dict[str, str] = {}


# Per-group Jupyter-check opt-in, populated in main() from `test_jupyter:`
# manifest fields. When True, `create_pod` adds the JUPYTER_PASSWORD env var
# and exposes :8888, and `test_pair` runs `run_jupyter_check` after the CUDA
# functional check.
GROUP_TEST_JUPYTER: dict[str, bool] = {}

# Password we hand to start.sh via env. Not a secret — every pod we spin up
# is auto-terminated within AUTO_TERMINATE and is only reachable through
# RunPod's authenticated proxy. We just need ANY non-empty value so start.sh
# decides to launch Jupyter (see start.sh: `if [[ $JUPYTER_PASSWORD ]]`).
JUPYTER_TEST_PASSWORD = "admin"
# Jupyter Lab is started in background by start.sh AFTER it prints "Pod is
# ready", so a brief startup grace is needed before we probe.
JUPYTER_WAIT_TIMEOUT = int(os.environ.get("JUPYTER_WAIT_TIMEOUT", "30"))


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
    # "This machine does not have the resources to deploy your pod. Please
    # try a different machine" — RunPod returns this when a candidate host
    # was picked but couldn't actually fit the pod (vRAM, disk, CPU). Same
    # remediation as "no capacity": move on to the next instance type.
    r"|does\s+not\s+have\s+the\s+resources"
    r"|try\s+a\s+different\s+machine"
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
            # Strip optional surrounding quotes so `min_cuda_version: "13.0"`
            # is parsed identically to `min_cuda_version: 13.0`. Numeric
            # and bool coercion are attempted only on unquoted values.
            quoted = len(value) >= 2 and (
                (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
            )
            if quoted:
                value = value[1:-1]
            parsed: object
            if quoted:
                parsed = value
            elif _TRUE_RE.match(value):
                parsed = True
            elif _FALSE_RE.match(value):
                parsed = False
            else:
                try:
                    parsed = (
                        int(value) if value.lstrip("-").isdigit() else float(value)
                    )
                except ValueError:
                    parsed = value
            data[group][key] = parsed
            current_list = None
        elif stripped.startswith("- ") and current_list is not None:
            item = stripped[2:].strip()
            # Strip optional surrounding quotes so users can write
            # `- "*Blackwell*"` (needed if they want the leading `*` to
            # avoid confusing a stricter YAML parser later). YAML treats
            # both forms identically — we do too.
            if len(item) >= 2 and (
                (item[0] == item[-1] == '"')
                or (item[0] == item[-1] == "'")
            ):
                item = item[1:-1]
            current_list.append(item)
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


def _apply_exclude_filter(
    names: list[str],
    patterns: list[str],
    *,
    group_name: str,
) -> list[str]:
    """Drop entries from `names` that match any fnmatch-style pattern in
    `patterns` (case-insensitive). Returns the survivors and logs whatever
    was excluded so the user can verify they didn't accidentally nuke
    everything.

    Pattern examples:
        "*Blackwell*"  — substring match (any GPU containing 'Blackwell')
        "RTX A4000"    — exact match
        "RTX*"         — prefix match
    """
    if not patterns:
        return names
    import fnmatch
    survivors: list[str] = []
    dropped: list[tuple[str, str]] = []  # (name, pattern_that_matched)
    norm_patterns = [p.lower() for p in patterns]
    for name in names:
        match = next(
            (p for p in norm_patterns if fnmatch.fnmatchcase(name.lower(), p)),
            None,
        )
        if match:
            dropped.append((name, match))
        else:
            survivors.append(name)
    if dropped:
        log(
            f"group '{group_name}': exclude_instances dropped "
            f"{len(dropped)} instance(s):"
        )
        for name, pat in dropped:
            log(f"  - {name!r} matched pattern {pat!r}", indent=1)
    elif patterns:
        log(
            f"group '{group_name}': exclude_instances had {len(patterns)} "
            "pattern(s) but matched nothing in the candidate list — check "
            "spelling/casing or remove dead entries from the manifest",
        )
    return survivors


def resolve_instances(group_name: str, group_config: dict) -> list[str]:
    """Decide which GPU display names this group should try, in order.

    Priority:
      0. CPU groups (name == 'base_cpu') — runpodctl 2.3.0 can't pick a
         specific CPU flavor; we return a single sentinel value so the
         caller's per-instance loop runs exactly once with --compute-type CPU.
      1. Explicit `instances:` list in the manifest — wins, used as-is.
      2. `max_price_per_hour: X` (+ optional `min_vram_gb`, `manufacturer`)
         — auto-pick from RunPod catalog, sorted cheapest first.

    After candidate selection, an optional `exclude_instances:` list of
    fnmatch-style patterns is subtracted. Use this to block known-bad
    matches like Blackwell GPUs on PyTorch 2.6 builds (no sm_120 kernels):

        pytorch:
            max_price_per_hour: 1.0
            exclude_instances:
            - "*Blackwell*"

    Returns [] when neither is set (caller will SKIP the group).
    """
    if group_name == "base_cpu":
        return [CPU_INSTANCE_SENTINEL]

    exclude_patterns = list(group_config.get("exclude_instances") or [])

    explicit = group_config.get("instances") or []
    if explicit:
        return _apply_exclude_filter(
            list(explicit), exclude_patterns, group_name=group_name
        )

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
    names = [name for _, name in candidates]
    return _apply_exclude_filter(
        names, exclude_patterns, group_name=group_name
    )


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


# Sentinel `instance` value used by CPU groups in place of a GPU display name.
# resolve_instances() returns this for CPU groups so the per-instance loop in
# test_image() runs exactly once; test_pair() recognises it and switches into
# the CPU pod-create path (no --gpu-id, --compute-type CPU).
CPU_INSTANCE_SENTINEL = "__cpu_auto__"


def create_pod(
    image: str,
    gpu_id: str,
    name: str,
    *,
    compute_type: str = "GPU",
    group: Optional[str] = None,
    test_jupyter: bool = False,
) -> tuple[Optional[str], str]:
    """Create a pod via `runpodctl pod create`. Returns (pod_id, raw_output).

    compute_type='GPU' uses --gpu-id to target a specific GPU type (caller
    must pass a non-empty gpu_id).
    compute_type='CPU' creates a CPU pod; runpodctl 2.3.0 does NOT let us
    pick a specific CPU flavor (--gpu-id is rejected for CPU), so RunPod
    chooses one for us. gpu_id is ignored in CPU mode.

    `group` is used to look up `min_cuda_version` from the manifest when the
    image tag doesn't encode a CUDA version (e.g. NGC `nvidia-pytorch:25.11`).

    `test_jupyter=True` expands the pod config so JupyterLab can be tested:
        - `--ports` gains `8888/http`
        - `--env` sets `JUPYTER_PASSWORD` (the value start.sh checks before
          starting Jupyter)
    """
    disk_gb = CPU_DISK_GB if compute_type == "CPU" else DISK_GB
    ports = ["22/tcp"]
    if test_jupyter:
        ports.append("8888/http")
    args = [
        "pod", "create",
        "--image", image,
        "--cloud-type", CLOUD_TYPE,
        "--container-disk-in-gb", str(disk_gb),
        "--ports", ",".join(ports),
        "--name", name,
        "--terminate-after", AUTO_TERMINATE,
        "-o", "json",
    ]
    if test_jupyter:
        # runpodctl wants --env as a single JSON-object string.
        env_obj = {"JUPYTER_PASSWORD": JUPYTER_TEST_PASSWORD}
        args.extend(["--env", json.dumps(env_obj)])
    if compute_type == "CPU":
        args.extend(["--compute-type", "CPU"])
        # CPU images have no CUDA, no GPU — `--min-cuda-version` would be
        # nonsensical and `--gpu-id` is rejected by runpodctl for CPU pods.
    else:
        args.extend(["--gpu-id", gpu_id, "--gpu-count", "1"])
        # Constrain scheduling to hosts whose driver supports this image's
        # CUDA. Without this, RunPod may land a cu13.0 image on an
        # older-driver host and the container fails at startup with
        # `nvidia-container-cli: cuda>=13.0`. Image tag wins; the manifest
        # `min_cuda_version` is only consulted for opaque tags (NGC etc.).
        cuda_version = (
            detect_cuda_version(image)
            or (GROUP_MIN_CUDA.get(group) if group else None)
        )
        if cuda_version:
            args.extend(["--min-cuda-version", cuda_version])
    if REGISTRY_AUTH_ID:
        args.extend(["--registry-auth-id", REGISTRY_AUTH_ID])
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


def _image_expects_gpu(image: str) -> bool:
    """True if the image ref implies a GPU runtime (CUDA or ROCm) inside."""
    return bool(_GPU_TAG_RE.search(image))


def _image_expects_torch(image: str) -> bool:
    """True if the image ref implies PyTorch is importable from system Python."""
    return bool(_TORCH_TAG_RE.search(image))


def cuda_check_command(group: str, image: str) -> str:
    """Return a shell command that functionally validates the GPU/CUDA stack
    for a given image, or '' to skip the check (CPU images).

    Selection is driven by the IMAGE REF, not the manifest `group` name:
    new manifest groups added in the future won't silently skip the check.
    `group` is accepted for log/report context only.

    Logic:
        - has 'pytorch' / 'torch\\d' in ref          -> run torch.cuda check
          (covers runpod/pytorch, runpod/nvidia-pytorch, ROCm-pytorch bases)
        - has 'cuda' / 'cu\\d' / 'rocm' only         -> run nvidia-smi check
          (covers runpod/base GPU tags and autoresearch — torch in venv
          not visible to system python)
        - none of the above                          -> CPU image, no check

    The returned command MUST exit non-zero on failure so the SSH call can
    detect it. Output is captured for the run report.
    """
    if _image_expects_torch(image):
        # Use `python` (the runpod/base symlink /usr/local/bin/python ->
        # /usr/bin/python3.12), NOT `python3`. On Ubuntu 22.04 system `python3`
        # resolves to python3.10 — but pytorch/Dockerfile installs torch via
        # `python -m pip`, so torch only exists in python3.12's site-packages.
        # On 24.04 they happen to coincide. Using `python` is portable.
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


def run_cuda_check(host: str, port: int, group: str, image: str) -> tuple[bool, str]:
    """Run the GPU/CUDA functional check inside the pod over SSH.
    Returns (ok, output). ok=True when:
      * the image has no GPU check defined (treated as pass), OR
      * the remote command exits 0.
    output contains stdout+stderr for inclusion in the run log."""
    cmd = cuda_check_command(group, image)
    if not cmd:
        return True, "(no GPU check for this image)"
    ssh_cmd = [*_ssh_command_prefix(host, port), cmd]
    try:
        r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "cuda check timed out after 60s"
    except FileNotFoundError:
        return False, "ssh binary not found"
    combined = (r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


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
        f"  \"http://127.0.0.1:8888/api/status?token={JUPYTER_TEST_PASSWORD}\" "
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

    This validates the IN-POD side: start.sh launched Jupyter with the right
    interpreter, server bound to :8888, our token works.

    Returns (ok, output). ok=False when the SSH call itself failed, OR when
    jupyter probe exited non-zero (server not running / wrong token / API
    not healthy)."""
    cmd = jupyter_check_command(JUPYTER_WAIT_TIMEOUT)
    ssh_cmd = [*_ssh_command_prefix(host, port), cmd]
    # SSH command has its own grace loop (JUPYTER_WAIT_TIMEOUT) plus a 10s
    # curl; pad the outer timeout to leave room for SSH handshake.
    outer_timeout = JUPYTER_WAIT_TIMEOUT + 30
    try:
        r = subprocess.run(
            ssh_cmd, capture_output=True, text=True, timeout=outer_timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"jupyter check timed out after {outer_timeout}s"
    except FileNotFoundError:
        return False, "ssh binary not found"
    combined = (r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


# RunPod exposes any port declared as `<port>/http` through its public proxy
# at `https://<pod-id>-<port>.proxy.runpod.net`. We hit this URL from the
# test machine so we validate the END-USER path, not just the in-pod side.
# The proxy takes a few seconds to register newly-exposed ports, so retry.
JUPYTER_PROXY_TIMEOUT = int(os.environ.get("JUPYTER_PROXY_TIMEOUT", "60"))


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
    import urllib.error
    import urllib.request

    url = (
        f"https://{pod_id}-8888.proxy.runpod.net/api/status"
        f"?token={JUPYTER_TEST_PASSWORD}"
    )
    deadline = time.monotonic() + JUPYTER_PROXY_TIMEOUT
    lines = [f"GET {url}"]
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
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            lines.append(f"attempt #{attempt}: {last_err}")
        time.sleep(5)

    lines.append(
        f"FAIL: proxy unreachable after {JUPYTER_PROXY_TIMEOUT}s "
        f"({attempt} attempts), last error: {last_err}"
    )
    return False, "\n".join(lines)


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


def test_pair(image: str, instance: str, group: str) -> tuple[str, str]:
    """Returns (status, detail). Statuses:
        'PASS'         — image booted, CUDA check OK, survived dwell
        'FAIL'         — pod was created and the CONTAINER itself proved
                         broken (crashed, CUDA failed, terminal state).
                         Moving to another GPU won't help, the image is bad.
                         `detail` describes which check failed.
        'CREATE_FAIL'  — pod-create returned a non-capacity, non-transient
                         error (bad image tag, registry auth, malformed
                         request, etc.). Like FAIL — another GPU won't fix
                         it. Distinct so the summary doesn't mis-attribute
                         the failure to the container. `detail` is the raw
                         orchestrator error.
        'UNAVAILABLE'  — RunPod has no capacity for this instance — try next
        'STUCK'        — pod was created but RunPod never assigned an SSH
                         endpoint within CREATE_TIMEOUT. Almost always a bad
                         host in the scheduler pool, not an image bug — caller
                         should try a different instance type.

    `group` is the manifest section name (e.g. 'pytorch', 'base_gpu') and is
    used to select the appropriate GPU/CUDA functional check."""
    is_cpu = instance == CPU_INSTANCE_SENTINEL
    if is_cpu:
        gpu_id = ""
        log("attempt: CPU pod (--compute-type CPU, flavor chosen by RunPod)",
            indent=1)
    else:
        gpu_id = resolve_gpu_id(instance)
        cuda = detect_cuda_version(image) or GROUP_MIN_CUDA.get(group)
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
        pod_id, raw = create_pod(
            image, gpu_id, name,
            compute_type="CPU" if is_cpu else "GPU",
            group=group,
            test_jupyter=GROUP_TEST_JUPYTER.get(group, False),
        )
        if pod_id:
            break
        if UNAVAILABLE_RE.search(raw):
            log(f"instance unavailable, will try next ({raw[:120]})", indent=2)
            return "UNAVAILABLE", ""
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
        return "CREATE_FAIL", f"pod create failed: {raw[:200].strip()}"

    if not pod_id:
        log(f"pod create failed after {CREATE_RETRIES} attempts: {raw[:200]}",
            indent=2)
        return "CREATE_FAIL", (
            f"pod create failed after {CREATE_RETRIES} attempts: "
            f"{raw[:200].strip()}"
        )

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
                return "STUCK", ""
            log(f"{state.lower()} -- {detail} -- FAIL", indent=2)
            dump_pod_logs(pod_id)
            return "FAIL", f"pod entered {state} state: {detail}"

        log(f"smoke check passed: {detail}", indent=2)

        # Run the per-group CUDA/GPU functional check. This is the real
        # "does this image actually work" gate — distinct from "did it boot".
        st = pod_state(pod_id)
        host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
        if host and port and cuda_check_command(group, image):
            log(f"running GPU/CUDA functional check for group '{group}'...", indent=2)
            ok, output = run_cuda_check(host, int(port), group, image)
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log("cuda check FAILED -- image broken", indent=2)
                dump_pod_logs(pod_id)
                return "FAIL", "CUDA/GPU functional check failed"
            log("cuda check passed", indent=2)

        # Jupyter checks: only when the group opted in via `test_jupyter`.
        # Two stages, both must pass:
        #   1. IN-POD: SSH into the pod and probe 127.0.0.1:8888. Catches
        #      start.sh regressions (e.g. wrong python interpreter for
        #      `-m jupyter`) that don't surface in container stdout.
        #   2. PROXY: from the test machine, hit
        #      https://<pod-id>-8888.proxy.runpod.net/. Catches port-type
        #      mistakes (`8888/tcp` instead of `8888/http`) — proxy never
        #      registers a non-http port, so end users can't reach Jupyter
        #      even though the in-pod check would happily pass.
        if host and port and GROUP_TEST_JUPYTER.get(group, False):
            log(
                f"running Jupyter Lab check (in-pod) for group '{group}'...",
                indent=2,
            )
            ok, output = run_jupyter_check(host, int(port))
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log(
                    "jupyter check (in-pod) FAILED -- start.sh did not "
                    "bring up JupyterLab",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "FAIL", "Jupyter Lab check failed (in-pod)"
            log("jupyter check (in-pod) passed", indent=2)

            log(
                f"running Jupyter Lab check (public proxy) for pod "
                f"{pod_id}...",
                indent=2,
            )
            ok, output = run_jupyter_proxy_check(pod_id)
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log(
                    "jupyter check (public proxy) FAILED -- port likely "
                    "not exposed as 8888/http",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "FAIL", "Jupyter Lab check failed (public proxy)"
            log("jupyter check (public proxy) passed", indent=2)

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
                    return "FAIL", (
                        "container crashed after initial boot "
                        f"({DWELL_SEC}s dwell re-probe failed: {err})"
                    )

        dump_pod_logs(pod_id)
        return "PASS", ""
    finally:
        # Always clean up this specific pod, even on exception.
        cleanup_pod(pod_id)


def test_image(
    image: str, instances: list[str], group: str
) -> tuple[str, str, str]:
    """Returns (status, note, instance_used).

    `instance_used` is the GPU display name that produced the terminal
    status. For PASS / FAIL it's the actual instance the test landed on.
    For SKIP (no capacity / all stuck), it's an empty string — the test
    never settled on any one instance.

    Iterates instance types until one PASSes. Stops early on FAIL (real image
    bug — no point trying another GPU). UNAVAILABLE (capacity) and STUCK
    (RunPod gave us a dead host) just move on to the next instance.
    CREATE_FAIL also short-circuits: a non-capacity orchestrator error
    (e.g. bad image tag, registry auth) won't be fixed by another GPU.
    """
    log(f"image: {image}")
    stuck_instances: list[str] = []
    last_create_error = ""
    last_create_inst = ""
    for inst in instances:
        result, detail = test_pair(image, inst, group)
        if result == "PASS":
            return "PASS", "", inst
        if result == "FAIL":
            return (
                "FAIL",
                detail or "container did not stay healthy",
                inst,
            )
        if result == "CREATE_FAIL":
            # Last create error is most informative — capacity-shortage 5xx
            # would have been UNAVAILABLE, so this is a genuine orchestrator
            # rejection. Try one more instance in case it's instance-specific,
            # but remember the error in case all fail.
            last_create_error = detail
            last_create_inst = inst
            continue
        if result == "STUCK":
            stuck_instances.append(inst)
        # UNAVAILABLE: silently try next
    if last_create_error:
        # We never got past pod-create on any instance and the errors weren't
        # capacity-shortages. Surface the last orchestrator error — this is
        # usually an image / auth / registry problem.
        return "FAIL", last_create_error, last_create_inst
    if stuck_instances:
        # We tried every instance and RunPod never gave us a working host on
        # any of them — surface that distinctly from "no capacity at all".
        log(
            f"all {len(instances)} instances either unavailable or stuck "
            f"(stuck: {stuck_instances})",
            indent=1,
        )
        return (
            "SKIP",
            (
                f"RunPod never assigned an SSH endpoint on "
                f"{len(stuck_instances)} instance type(s) — likely a "
                "scheduler issue, try again later"
            ),
            "",
        )
    log(f"all {len(instances)} instances unavailable (no capacity)", indent=1)
    return (
        "SKIP",
        f"no capacity on any of {len(instances)} candidate instance type(s)",
        "",
    )


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

    # Collect manifest `min_cuda_version` fallbacks. Used by create_pod when
    # an image tag doesn't encode CUDA itself (NGC `nvidia-pytorch:25.11`).
    for grp, contents in manifest.items():
        normalized = _normalize_cuda_version(contents.get("min_cuda_version"))
        if normalized:
            GROUP_MIN_CUDA[grp] = normalized
            log(
                f"group '{grp}': min_cuda_version={normalized} "
                "(applied when image tag has no embedded CUDA)"
            )

    # Collect manifest `test_jupyter` opt-ins. Drives both pod creation
    # (env + port) and the post-boot Jupyter probe.
    for grp, contents in manifest.items():
        flag = _normalize_bool(contents.get("test_jupyter"))
        if flag:
            GROUP_TEST_JUPYTER[grp] = True
            log(
                f"group '{grp}': test_jupyter=true "
                f"(JUPYTER_PASSWORD={JUPYTER_TEST_PASSWORD!r}, expose 8888/http)"
            )

    # Resolve the instances list for each group now (so we can warn about
    # typos / empty lists once, up front, instead of per-job). For
    # explicit-list groups this is just a copy. For budget-based groups this
    # queries the GPU_CATALOG and picks cheapest-first. For `base_cpu` it
    # returns a single sentinel value (RunPod picks the CPU flavor).
    resolved_instances: dict[str, list[str]] = {}
    for grp, contents in manifest.items():
        resolved_instances[grp] = resolve_instances(grp, contents)

    # Warn about explicit-list entries that don't match any known GPU display
    # name — these would be passed to runpodctl verbatim and fail. Skip the
    # CPU sentinel since it isn't a GPU name by design.
    unmapped = sorted({
        inst
        for grp, instances in resolved_instances.items()
        for inst in instances
        if inst != CPU_INSTANCE_SENTINEL and not is_known_gpu(inst)
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

    # results[image] = (status, note, instance_used). `instance_used` lets
    # the summary report which GPU each test landed on (handy when an image
    # FAILed because of an unlucky host pairing, not an actual bug).
    results: dict[str, tuple[str, str, str]] = {}

    # Flatten the manifest into a list of (image, group, instances) jobs that
    # can run independently. Skip groups we can't actually exercise.
    jobs: list[tuple[str, str, list[str]]] = []
    for group, contents in manifest.items():
        if group_filter and group != group_filter:
            continue
        instances = resolved_instances.get(group, [])
        if not instances:
            log(
                f"skipping group '{group}': no instances resolved "
                "(neither 'instances:' nor 'max_price_per_hour:' produced "
                "any candidates)"
            )
            for img in contents.get("images", []):
                results[img] = ("SKIP", "no instances configured", "")
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
    for status, _, _ in results.values():
        counts[status] += 1
    print(
        f"totals: {counts['PASS']} PASS, "
        f"{counts['FAIL']} FAIL, "
        f"{counts['SKIP']} SKIP\n"
    )
    for want in ("FAIL", "SKIP", "PASS"):
        for img, (status, note, instance) in results.items():
            if status != want:
                continue
            # CPU sentinel ('__cpu_auto__') would just be noise in the
            # summary — translate it to a readable label.
            inst_label = "CPU" if instance == CPU_INSTANCE_SENTINEL else instance
            inst_str = f" [{inst_label}]" if inst_label else ""
            note_str = f" -- {note}" if note else ""
            print(f"  {want:6s} {img}{inst_str}{note_str}")

    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
