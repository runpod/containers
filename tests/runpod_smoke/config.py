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

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.dirname(_PKG_DIR)

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

# What to do when at least one image ended up SKIPped. SKIPs mean the
# test never actually ran against the image — RunPod had no capacity
# on every candidate, or every candidate landed on a stuck host. In CI
# that's effectively zero validation, so the default is strict ('fail').
# Modes:
#   'fail' — exit 1 + GitHub `::error::` annotation. Job goes red.
#            Use when SKIPped means "we didn't prove the image works
#            and we MUST know about that".
#   'warn' — exit 0 + GitHub `::warning::` annotation. Job stays green
#            but the run shows a yellow warning bubble in the PR check
#            tab. Use when capacity-shortage is expected (tight DCs)
#            and you'd rather not block PRs on RunPod's free capacity,
#            but you still want a visible signal.
#   'pass' — exit 0, no annotation. Legacy lenient behaviour, no signal
#            at all. Avoid unless you have downstream tooling that
#            scrapes the summary directly.
# Unknown values fall back to 'fail' so a typo never silently switches
# the safer default off. FAIL outcomes (broken container) are ALWAYS
# fatal regardless of this knob.
_ON_SKIP_VALID = ("fail", "warn", "pass")


def _coerce_on_skip(raw: str) -> str:
    val = (raw or "").strip().lower()
    return val if val in _ON_SKIP_VALID else "fail"


ON_SKIP: str = _coerce_on_skip(os.environ.get("ON_SKIP", "fail"))

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
# `GET /v2/registries`.
#
# REGISTRY_AUTH_ID is reassigned by main() after auto-discovery — access
# it via `config.REGISTRY_AUTH_ID` (not a bare `from config import`) to
# pick up the post-discovery value.
REGISTRY_AUTH_ID = os.environ.get("REGISTRY_AUTH_ID", "")
REGISTRY_AUTH_NAME = os.environ.get("REGISTRY_AUTH_NAME", "")

# NO server-side auto-terminate any more. The old CLI took
# `--terminate-after <RFC3339>`, which self-destructed anything we leaked
# (crash before cleanup, or a GitHub Actions `cancel-in-progress` that
# SIGKILLs us mid-cleanup_all). REST API v2 has no equivalent field, so
# .github/workflows/reap-pods.yml — hourly, deletes `smoketest-*` older
# than 60 min — is now the ONLY backstop. Keep it healthy.


# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------

# REST API v2 is the primary log source; SSH is retained only for the GPU
# SMI diagnostic. The endpoint comes from `ssh.direct` on GET /v2/pods/{id}
# once the pod is scheduled.
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
# Container logs via REST API (v2)
# ---------------------------------------------------------------------------

# `GET /v2/pods/{id}/logs` streams container stdout as SSE — the one source
# SSH cannot read (PID-1 stdout is not readable from a separate process).
# The same API is used for the always-on error scan and diagnostic dumps.
#   LOG_ERROR_SCAN=0        disables the error-scan step
#   LOG_ERROR_PATTERN=...   overrides the case-insensitive regex
#   LOG_API_TAIL=N          historical lines to backfill (max 5000)
LOG_ERROR_SCAN = os.environ.get("LOG_ERROR_SCAN", "1") == "1"
LOG_ERROR_PATTERN = os.environ.get(
    "LOG_ERROR_PATTERN", r"\berr(or)?s?\b|\bcrash(ed|es|ing)?\b"
)
LOG_API_TAIL = int(os.environ.get("LOG_API_TAIL", "1000"))

# System logs contain host-side failures that never reach container stdout:
# image-pull errors and `runc` container-init aborts, for example.
SYS_LOG_ERROR_PATTERN = os.environ.get(
    "SYS_LOG_ERROR_PATTERN",
    r"\berr(or)?s?\b|\bfail(ed|ure)?\b|\bcrash(ed|es|ing)?\b",
)


# ---------------------------------------------------------------------------
# Jupyter
# ---------------------------------------------------------------------------

# Password we hand to start.sh via env. Not a secret — every pod we spin
# up is short-lived (reaped within the hour) and is only reachable through
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
# Generic per-port checks (test_ports manifest field)
# ---------------------------------------------------------------------------

# Each requested port is exposed as `<port>/http` and checked proxy-first.
# These independent limits include both app cold-start and proxy registration.
PORT_WAIT_TIMEOUT = int(os.environ.get("PORT_WAIT_TIMEOUT", "300"))
PORT_PROXY_TIMEOUT = int(os.environ.get("PORT_PROXY_TIMEOUT", "300"))

# ComfyUI listens on this HTTP port. `test_comfyui` exposes it as
# `<port>/http` and runs a labelled proxy-first reachability check.
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_WORKFLOW = os.environ.get(
    "COMFYUI_WORKFLOW",
    os.path.join(_TESTS_DIR, "comfyui", "workflows", "gsl_starter_1_1.api.json"),
)
COMFYUI_MODELS_MANIFEST = os.environ.get(
    "COMFYUI_MODELS_MANIFEST",
    os.path.join(_TESTS_DIR, "comfyui", "models.json"),
)
COMFYUI_WAIT_TIMEOUT = int(os.environ.get("COMFYUI_WAIT_TIMEOUT", "600"))
COMFYUI_ROUTES_TIMEOUT = int(os.environ.get("COMFYUI_ROUTES_TIMEOUT", "60"))
COMFYUI_DOWNLOAD_TIMEOUT = int(os.environ.get("COMFYUI_DOWNLOAD_TIMEOUT", "900"))
COMFYUI_GEN_TIMEOUT = int(os.environ.get("COMFYUI_GEN_TIMEOUT", "300"))
COMFYUI_SAVE_DIR = os.environ.get("COMFYUI_SAVE_DIR", "")


# ---------------------------------------------------------------------------
# CPU groups + candidates
# ---------------------------------------------------------------------------

# Manifest group names that should be treated as CPU pods. Centralised
# here (rather than a bare string match deep in instances.py) so adding a
# second CPU-flavoured group later is one frozenset edit, not a grep-
# and-rename hunt. `instances.resolve_instances` expands each of these
# groups into one entry per `CPU_CANDIDATES` label instead of consulting
# the manifest's `instances:` / `max_price_per_hour:` fields.
#
# Keep in sync with `.github/scripts/generate_test_manifest.py` which
# emits 'base_cpu' as the CPU group name for the `base` profile.
CPU_GROUP_NAMES: frozenset[str] = frozenset({"base_cpu"})


# CPU "instance" candidates.
#
# The flavor itself (`cpu.id` + `vcpuCount`) is chosen by
# `instances.pick_cpu_flavor` from GET /v2/catalog/cpus. What varies between
# candidates is placement, so that a full pool in one cloud doesn't end the
# attempt:
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


# CPU flavors from GET /v2/catalog/cpus, populated at startup. v2 requires
# an explicit `cpu.id` + `vcpuCount` on pod create, unlike the old CLI which
# let RunPod pick — so we choose the cheapest fitting flavor ourselves.
CPU_CATALOG: list[dict] = []

# vCPU count requested for CPU pods. Must be a power of two and inside the
# chosen flavor's `vcpu.min..max`. 4 is the smallest that every flavor
# offers and is plenty for a boot-and-dwell smoke test.
CPU_VCPU_COUNT = int(os.environ.get("CPU_VCPU_COUNT", "4"))

# Pin a specific CPU flavor id (e.g. 'cpu5c') instead of auto-picking the
# cheapest one. Empty = auto.
CPU_FLAVOR_ID = os.environ.get("CPU_FLAVOR_ID", "")


@dataclass(frozen=True)
class CpuCandidate:
    """One CPU pod-create attempt — varied along cloud and data centre.
    The flavor itself is chosen by `instances.pick_cpu_flavor`."""
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


def is_cpu_instance(instance: str) -> bool:
    """True if `instance` is one of the CPU candidate labels. Call sites
    use this rather than checking dict membership directly so the rule
    stays in one place if we ever add more CPU-ish synthetic labels."""
    return instance in CPU_CANDIDATES


def cpu_candidate_for(instance: str) -> CpuCandidate:
    """Look up the CpuCandidate for a label. Unknown labels fall back to
    a CLOUD_TYPE-default candidate rather than crashing — a stale
    `instances:` entry in the manifest shouldn't bring the whole
    smoke-test down."""
    return CPU_CANDIDATES.get(
        instance, CpuCandidate(cloud_type=CLOUD_TYPE)
    )


# ---------------------------------------------------------------------------
# Shared mutable state (populated at startup / from the manifest)
# ---------------------------------------------------------------------------

# Display-name -> gpu id mapping, populated at startup from
# `GET /v2/catalog/gpus`. Keeps the YAML manifest free
# of RunPod-internal gpuId strings — users only put display names there.
GPU_ID_MAP: dict[str, str] = {}

# GPU catalog with pricing. Populated at startup via GraphQL since
# Populated from GET /v2/catalog/gpus. Used for budget-based
# instance selection (manifest's `max_price_per_hour`). Empty list if API
# unreachable; in that case budget filters silently no-op and the script
# falls back to whatever's in the manifest's explicit `instances:` list.
GPU_CATALOG: list[dict] = []

# Per-group fallback CUDA version, populated in main() from the
# `min_cuda_version:` manifest field. Looked up by `pod.create_pod` ONLY
# when `instances.detect_cuda_version(image)` returns None (i.e. image
# tag has no embedded CUDA — NGC `nvidia-pytorch:25.11` and similar
# opaque tags).
#
# Despite the "min" naming (which matches the API's underlying
# `--min-cuda-version` flag), this field is a FALLBACK, not an override:
# if the tag contains `cu1281` / `cuda1300` / etc., the manifest value
# is silently ignored. By design — tag is the most accurate source for
# image-encoded CUDA, so manifest gets to fill the gap, not contradict.
# When ignored, `pod.create_pod` emits a one-line trace so the operator
# notices.
GROUP_MIN_CUDA: dict[str, str] = {}

# Per-group CUDA axis, populated from the `cuda_versions:` manifest field.
# When active, each candidate GPU is expanded into one job per CUDA version
# it actually offers, and the version is pinned via
# `gpu.allowedCudaVersions`. That overrides GROUP_MIN_CUDA for the group,
# because the API rejects allowedCudaVersions and minCudaVersion together.
#
#   GROUP_CUDA_VERSIONS — explicit versions asked for, e.g. ['12.8', '13.0']
#   GROUP_CUDA_ALL      — 'all': every version the GPU reports capacity for
GROUP_CUDA_VERSIONS: dict[str, list[str]] = {}
GROUP_CUDA_ALL: dict[str, bool] = {}

# Safety cap on the GPU x CUDA fan-out. A catalog-wide `all` sweep is ~34
# jobs today, but the fleet grows and a stray run shouldn't turn into a
# day of GPU time. Jobs past the cap are dropped with a warning.
MAX_CUDA_COMBOS = int(os.environ.get("MAX_CUDA_COMBOS", "120"))

# Per-group Jupyter-check opt-in, populated in main() from the
# `test_jupyter:` manifest field. When True, `pod.create_pod` adds the
# JUPYTER_PASSWORD env var and exposes :8888, and `runner.test_pair` runs
# the Jupyter probes after the CUDA functional check.
GROUP_TEST_JUPYTER: dict[str, bool] = {}

# Per-group HTTP ports populated from the optional `test_ports:` manifest
# list. They are exposed as `<port>/http` and checked through the public
# proxy first; SSH only diagnoses a proxy failure.
GROUP_TEST_PORTS: dict[str, list[int]] = {}

# ComfyUI-specific public-proxy reachability smoke.
GROUP_TEST_COMFYUI: dict[str, bool] = {}

# End-to-end ComfyUI generation test. It implies GROUP_TEST_COMFYUI so the
# public reachability check always runs before model provisioning.
GROUP_TEST_COMFYUI_FUNCTIONAL: dict[str, bool] = {}

# Compatibility-matrix opt-in. Each selected GPU becomes an independent job,
# rather than stopping after the first passing candidate.
GROUP_CHECK_ALL_GPU: dict[str, bool] = {}
