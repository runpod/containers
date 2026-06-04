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

# CPU "instance" candidates. runpodctl 2.3.0 doesn't expose a
# --cpu-flavor / --instance-id flag (--gpu-id is rejected for
# --compute-type CPU), so we steer RunPod's CPU-flavor picker via the
# resource-minimum flags it DOES accept: `--vcpu` (min vCPUs) and
# `--mem` (min RAM, GB). Different (vcpu, mem) asks land in different
# flavor pools — when the cheapest tier is saturated and pod-create
# returns "no capacity", a beefier ask often still has free machines.
# `instances.resolve_instances` returns each label as a separate
# "instance" so the existing per-instance retry loop in
# `runner.test_image` iterates over them just like it does for GPUs.
#
# Override via `CPU_FLAVORS` env. Format:
#   CPU_FLAVORS="label1:vcpu:mem,label2:vcpu:mem,..."
# vcpu/mem of 0 means "omit the flag" (let RunPod pick). Empty / malformed
# value falls back to DEFAULT_CPU_FLAVORS.


@dataclass(frozen=True)
class CpuFlavor:
    """RunPod CPU pod resource ask. vcpu / mem are MINIMUMS — RunPod
    rounds up to the cheapest flavor that fits. Setting either to 0
    omits the corresponding runpodctl flag entirely (lets the scheduler
    pick freely)."""
    vcpu: int
    mem: int


# First entry intentionally has no resource floor — matches the legacy
# 2.3.0 behaviour and lands on whatever cheapest CPU flavor RunPod has.
# The other two bump (vcpu, mem) to steer the scheduler into larger
# flavor pools when the cheap tier is fully booked. Smoke-test workload
# is trivial (boot + dwell), so the extra cost per attempt is ≪ $0.05.
DEFAULT_CPU_FLAVORS: dict[str, CpuFlavor] = {
    "cpu-default": CpuFlavor(vcpu=0, mem=0),
    "cpu-2vcpu-8gb": CpuFlavor(vcpu=2, mem=8),
    "cpu-4vcpu-16gb": CpuFlavor(vcpu=4, mem=16),
}


def _parse_cpu_flavors(raw: str) -> dict[str, CpuFlavor]:
    """Parse 'label:vcpu:mem,label:vcpu:mem,...' into a label→CpuFlavor
    mapping. Malformed entries are dropped silently; empty / all-malformed
    input falls back to DEFAULT_CPU_FLAVORS so the smoke-test never ends
    up with zero CPU candidates."""
    if not raw.strip():
        return DEFAULT_CPU_FLAVORS
    out: dict[str, CpuFlavor] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3:
            continue
        label, vcpu_s, mem_s = (p.strip() for p in parts)
        if not label:
            continue
        try:
            out[label] = CpuFlavor(vcpu=int(vcpu_s), mem=int(mem_s))
        except ValueError:
            continue
    return out or DEFAULT_CPU_FLAVORS


CPU_FLAVORS: dict[str, CpuFlavor] = _parse_cpu_flavors(
    os.environ.get("CPU_FLAVORS", "")
)


# Legacy single-sentinel kept for back-compat with anything that imported
# it (e.g. older `images:` manifests that hard-code `__cpu_auto__`). New
# code consults `is_cpu_instance()` instead of comparing strings directly.
CPU_INSTANCE_SENTINEL = "__cpu_auto__"


def is_cpu_instance(instance: str) -> bool:
    """True if `instance` is one of the CPU sentinels (legacy bare value
    or a label from CPU_FLAVORS). Used in place of
    `== CPU_INSTANCE_SENTINEL` so call sites don't have to know about
    the multi-flavor expansion."""
    return instance == CPU_INSTANCE_SENTINEL or instance in CPU_FLAVORS


def cpu_flavor_for(instance: str) -> CpuFlavor:
    """Look up the CpuFlavor for a CPU sentinel. The legacy bare
    `__cpu_auto__` returns a zeroed flavor (no --vcpu / --mem flags).
    Unknown labels also return zeroed flavor — safer than crashing
    in a smoke-test that's already trying its hardest to keep going."""
    if instance == CPU_INSTANCE_SENTINEL:
        return CpuFlavor(vcpu=0, mem=0)
    return CPU_FLAVORS.get(instance, CpuFlavor(vcpu=0, mem=0))


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
