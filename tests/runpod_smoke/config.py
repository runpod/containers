"""Module-level configuration and shared mutable state.

All env-derived knobs live here so the rest of the package doesn't need to
touch `os.environ` directly. The mutable-by-design globals (GPU catalog,
per-group manifest derivatives, registry auth id) also live here so call
sites read fresh values via `config.<NAME>` — `from config import NAME`
would capture them at import time and miss runtime updates from main().
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Pod / scheduling
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

# Treat any SKIP outcome as a job failure. SKIPs mean the test never
# actually ran against the image — RunPod had no capacity on every
# candidate instance type, or every candidate landed on a stuck host.
# In a CI smoke test that's effectively zero validation, so the default
# is strict (fail). Set FAIL_ON_SKIP=0 only when you knowingly accept
# capacity-shortage as non-fatal (e.g. a probe job that runs on a tight
# DC and you don't want flaky CI). FAIL outcomes are always fatal
# regardless of this flag.
FAIL_ON_SKIP = os.environ.get("FAIL_ON_SKIP", "1") == "1"

# How many times to retry pod-create when RunPod returns a transient
# orchestrator error ("Something went wrong", 502/503, etc.). Capacity-
# shortage errors are NOT retried (we move on to the next instance instead).
CREATE_RETRIES = int(os.environ.get("CREATE_RETRIES", "3"))
CREATE_RETRY_BACKOFF = int(os.environ.get("CREATE_RETRY_BACKOFF", "10"))

# How long a pod can sit in "no SSH endpoint yet" before we surface a hint
# about slow pulls / possible Docker Hub rate limit. Doesn't fail the pod
# — just an informational note in the logs.
STALL_HINT_AFTER = int(os.environ.get("STALL_HINT_AFTER", "180"))

# Docker Hub authenticated pulls — without this, RunPod datacenters share
# an anonymous IP pool that hits Docker Hub's `toomanyrequests` rate limit
# fast. Either set REGISTRY_AUTH_ID explicitly, or REGISTRY_AUTH_NAME to
# pick by display name, or the script auto-picks the first entry from
# `runpodctl registry list`.
#
# REGISTRY_AUTH_ID is reassigned by main() after auto-discovery — access
# it via `config.REGISTRY_AUTH_ID` (not a bare `from config import`) to
# pick up the post-discovery value.
REGISTRY_AUTH_ID = os.environ.get("REGISTRY_AUTH_ID", "")
REGISTRY_AUTH_NAME = os.environ.get("REGISTRY_AUTH_NAME", "")

# All pods we create carry this absolute deadline so anything we leak
# (e.g. crash before cleanup) auto-terminates within 2h.
AUTO_TERMINATE = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)


# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------

# Container logs aren't exposed via runpodctl 2.3.0's JSON, so we SSH
# directly to the pod's exposed port 22 (mapped to a random high port on
# a public IP by RunPod) to grab them. The endpoint is discovered from
# `pod get`'s ssh.ip / ssh.port fields once the pod is scheduled.
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
    # OpenSSH 8.7+ disables ssh-rsa (SHA-1) by default. The sshd inside
    # RunPod base images can still want legacy ssh-rsa for RSA client keys
    # (which is what runpodctl auto-generates), so we re-enable it
    # explicitly.
    "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o", "HostKeyAlgorithms=+ssh-rsa",
]


# ---------------------------------------------------------------------------
# Jupyter
# ---------------------------------------------------------------------------

# Password we hand to start.sh via env. Not a secret — every pod we spin
# up is auto-terminated within AUTO_TERMINATE and is only reachable through
# RunPod's authenticated proxy. We just need ANY non-empty value so start.sh
# decides to launch Jupyter (see start.sh: `if [[ $JUPYTER_PASSWORD ]]`).
JUPYTER_TEST_PASSWORD = "admin"

# Jupyter Lab is started in background by start.sh AFTER it prints "Pod is
# ready", so a brief startup grace is needed before we probe.
JUPYTER_WAIT_TIMEOUT = int(os.environ.get("JUPYTER_WAIT_TIMEOUT", "30"))

# RunPod exposes any port declared as `<port>/http` through its public
# proxy at `https://<pod-id>-<port>.proxy.runpod.net`. The proxy takes a
# few seconds to register newly-exposed ports — we retry up to this many
# seconds before giving up.
JUPYTER_PROXY_TIMEOUT = int(os.environ.get("JUPYTER_PROXY_TIMEOUT", "60"))


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

# CPU "instance" candidates.
#
# `runpodctl pod create` (the new subcommand we use) does NOT expose
# `--cpu-flavor`, `--vcpu`, or `--mem`. The legacy `runpodctl create pod`
# command does have them, but it's a different code path with different
# flags — the new command takes (`--compute-type CPU`, `--cloud-type`,
# optional `--data-center-ids`) and lets RunPod pick the cheapest CPU
# flavor that fits the container disk size for the chosen cloud + DC.
#
# To get MULTIPLE CPU "candidates" we vary the axes runpodctl actually
# accepts:
#   - cloud_type:        SECURE vs COMMUNITY. Totally different capacity
#                        pools — when SECURE is full, COMMUNITY almost
#                        always has free CPU hosts (and is cheaper).
#   - data_center_ids:   optional `--data-center-ids` csv. Use to pin a
#                        candidate to a specific DC or set of DCs (rare
#                        — usually leaving this empty is the best
#                        capacity strategy).
#
# `instances.resolve_instances` returns one entry per candidate label so
# the existing per-instance retry loop in `runner.test_image` walks them
# in order on UNAVAILABLE / STUCK, just like it does for GPU types.
#
# Override via `CPU_CANDIDATES` env. Format:
#   CPU_CANDIDATES="label:CLOUD[:DC1+DC2+...],label:CLOUD[:DC_CSV],..."
# Notes:
#   * `+` (not `,`) separates DC ids inside one candidate, so the outer
#     csv can stay comma-delimited without parser ambiguity.
#   * CLOUD must be SECURE or COMMUNITY (case-insensitive); anything else
#     drops the entry on the floor (malformed lines are silently
#     dropped, so a typo never crashes the run).
#   * Empty / all-malformed input falls back to DEFAULT_CPU_CANDIDATES.


@dataclass(frozen=True)
class CpuCandidate:
    """One CPU pod-create attempt — varied along the axes that
    `runpodctl pod create` exposes for CPU pods. RunPod's scheduler
    still picks the actual CPU flavor (vCPU/RAM tier) inside the chosen
    cloud + DC, based on container disk size."""
    cloud_type: str           # 'SECURE' or 'COMMUNITY'
    data_center_ids: str = ""  # comma-separated; "" = any DC in the cloud


# First entry is SECURE (matches the prior single-sentinel behaviour and
# what most images expect — secure cloud is the safer default). Second
# is COMMUNITY as a cheap, capacity-rich fallback: when SECURE returns
# "no capacity" the test loop moves to this candidate, and COMMUNITY
# almost always has free CPU hosts.
DEFAULT_CPU_CANDIDATES: dict[str, CpuCandidate] = {
    "cpu-secure":    CpuCandidate(cloud_type="SECURE"),
    "cpu-community": CpuCandidate(cloud_type="COMMUNITY"),
}


def _parse_cpu_candidates(raw: str) -> dict[str, CpuCandidate]:
    """Parse 'label:CLOUD[:DC1+DC2],...' into label→CpuCandidate mapping.
    Malformed entries are silently dropped; empty / all-broken input
    falls back to DEFAULT_CPU_CANDIDATES so the smoke-test never ends up
    with zero CPU candidates."""
    if not raw.strip():
        return DEFAULT_CPU_CANDIDATES
    out: dict[str, CpuCandidate] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) not in (2, 3):
            continue
        label = parts[0].strip()
        cloud = parts[1].strip().upper()
        if not label or cloud not in ("SECURE", "COMMUNITY"):
            continue
        dcs = parts[2].strip().replace("+", ",") if len(parts) == 3 else ""
        out[label] = CpuCandidate(cloud_type=cloud, data_center_ids=dcs)
    return out or DEFAULT_CPU_CANDIDATES


CPU_CANDIDATES: dict[str, CpuCandidate] = _parse_cpu_candidates(
    os.environ.get("CPU_CANDIDATES", "")
)


# Legacy single-sentinel kept for back-compat with anything that imported
# it (e.g. older code that hard-codes `__cpu_auto__`). New code consults
# `is_cpu_instance()` instead of comparing strings directly.
CPU_INSTANCE_SENTINEL = "__cpu_auto__"


def is_cpu_instance(instance: str) -> bool:
    """True if `instance` is one of the CPU sentinels (legacy bare value
    or a label from CPU_CANDIDATES). Used in place of
    `== CPU_INSTANCE_SENTINEL` so call sites don't need to know about
    the multi-candidate expansion."""
    return instance == CPU_INSTANCE_SENTINEL or instance in CPU_CANDIDATES


def cpu_candidate_for(instance: str) -> CpuCandidate:
    """Look up the CpuCandidate for a CPU sentinel. The legacy bare
    `__cpu_auto__` resolves to a candidate using the global CLOUD_TYPE
    with no DC pinning. Unknown labels fall back to the same defaults —
    safer than crashing inside a smoke-test loop."""
    if instance == CPU_INSTANCE_SENTINEL:
        return CpuCandidate(cloud_type=CLOUD_TYPE)
    return CPU_CANDIDATES.get(
        instance, CpuCandidate(cloud_type=CLOUD_TYPE)
    )


# ---------------------------------------------------------------------------
# Shared mutable state (populated at startup / from the manifest)
# ---------------------------------------------------------------------------

# Display-name -> runpodctl --gpu-id mapping. Populated at startup from
# `runpodctl gpu list --include-unavailable`. Keeps the YAML manifest free
# of RunPod-internal gpuId strings — users only put display names there.
GPU_ID_MAP: dict[str, str] = {}

# GPU catalog with pricing. Populated at startup via GraphQL since
# `runpodctl gpu list` does NOT include price fields. Used for budget-based
# instance selection (manifest's `max_price_per_hour`). Empty list if API
# unreachable; in that case budget filters silently no-op and the script
# falls back to whatever's in the manifest's explicit `instances:` list.
GPU_CATALOG: list[dict] = []

# Per-group fallback CUDA version, populated in main() from the
# `min_cuda_version:` manifest field. Looked up by `pod.create_pod` only
# when `instances.detect_cuda_version(image)` returns None (i.e. image tag
# has no embedded CUDA — NGC `nvidia-pytorch:25.11` and similar opaque tags).
GROUP_MIN_CUDA: dict[str, str] = {}

# Per-group Jupyter-check opt-in, populated in main() from the
# `test_jupyter:` manifest field. When True, `pod.create_pod` adds the
# JUPYTER_PASSWORD env var and exposes :8888, and `runner.test_pair` runs
# the Jupyter probes after the CUDA functional check.
GROUP_TEST_JUPYTER: dict[str, bool] = {}
