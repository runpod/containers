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
# Target environment
# ---------------------------------------------------------------------------

# Which RunPod environment to provision in. Prod is the default; cluster
# groups additionally need ALLOW_PROD_CLUSTERS=1 there (CI sets it). The
# API key must belong to the same environment — a prod key is rejected by dev and vice
# versa.
VALID_ENVS = ("prod", "dev")
_ENV_DEFAULTS = {
    # (API origin, pod HTTP proxy domain)
    "prod": ("https://api.runpod.io", "proxy.runpod.net"),
    "dev": ("https://api.runpod.dev", "dev-proxy.runpod.net"),
}
RUNPOD_ENV = os.environ.get("RUNPOD_ENV", "prod").strip().lower() or "prod"
_api_default, _proxy_default = _ENV_DEFAULTS.get(RUNPOD_ENV, _ENV_DEFAULTS["prod"])
# Overrides for a one-off host (staging, a local API). REST v2 lives under
# `<origin>/v2`, GraphQL under `<origin>/graphql`.
API_ORIGIN = os.environ.get("RUNPOD_API_ORIGIN", _api_default).rstrip("/")
REST_URL = f"{API_ORIGIN}/v2"
GRAPHQL_URL = f"{API_ORIGIN}/graphql"
# `<pod-id>-<port>.<PROXY_DOMAIN>` serves every `<port>/http` the pod exposes.
PROXY_DOMAIN = os.environ.get("RUNPOD_PROXY_DOMAIN", _proxy_default).strip(".")


def proxy_url(pod_id: str, port: int) -> str:
    """Public HTTPS origin for one of the pod's `<port>/http` ports."""
    return f"https://{pod_id}-{port}.{PROXY_DOMAIN}"


# ---------------------------------------------------------------------------
# Pod / scheduling
# ---------------------------------------------------------------------------

VALID_CLOUDS = ("SECURE", "COMMUNITY")


def _parse_cloud_types(raw: str) -> list[str]:
    """One tier, a comma-separated list, or `ALL`. Unknown names are dropped."""
    wanted = [part.strip().upper() for part in raw.split(",") if part.strip()]
    if "ALL" in wanted:
        return list(VALID_CLOUDS)
    ordered = [c for c in VALID_CLOUDS if c in wanted]
    return ordered or ["SECURE"]


# The catalog's `cudaVersions` and availability are scoped to one tier and the
# tiers do not nest, so full coverage needs a planning pass each. CLOUD_TYPES
# is every requested tier; CLOUD_TYPE is the one being planned right now.
CLOUD_TYPES = _parse_cloud_types(os.environ.get("CLOUD_TYPE", "SECURE"))
CLOUD_TYPE = CLOUD_TYPES[0]
DISK_GB = int(os.environ.get("DISK_GB", "100"))
# CPU pods on Runpod cap container disk by flavor: the cheapest flavors
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
# Keep modest: Runpod has per-account rate limits, and your wallet has limits
# too (DISK_GB * pods * hours can add up).
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "1"))

# What to do when at least one image ended up SKIPped. SKIPs mean the
# test never actually ran against the image — Runpod had no capacity
# on every candidate, or every candidate landed on a stuck host. In CI
# that's effectively zero validation, so the default is strict ('fail').
# Modes:
#   'fail' — exit 1 + GitHub `::error::` annotation. Job goes red.
#            Use when SKIPped means "we didn't prove the image works
#            and we MUST know about that".
#   'warn' — exit 0 + GitHub `::warning::` annotation. Job stays green
#            but the run shows a yellow warning bubble in the PR check
#            tab. Use when capacity-shortage is expected (tight DCs)
#            and you'd rather not block PRs on Runpod's free capacity,
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

# How many times to retry pod-create when Runpod returns a transient
# orchestrator error ("Something went wrong", 502/503, etc.). Capacity-
# shortage errors are NOT retried (we move on to the next instance instead).
CREATE_RETRIES = int(os.environ.get("CREATE_RETRIES", "3"))
CREATE_RETRY_BACKOFF = int(os.environ.get("CREATE_RETRY_BACKOFF", "10"))

# Whole-job retries for SKIP / UNVERIFIED (every candidate had no capacity,
# or the host never answered). After the first pass, those jobs — and only
# those — are re-run up to SKIP_RETRIES more times, waiting
# SKIP_RETRY_DELAY * attempt seconds before each round (5, 10, 15, 20, 25 min
# by default; see SKIP_RETRY_BACKOFF). FAIL is never retried. Disabled under
# ON_SKIP=pass. Set SKIP_RETRIES=0 to turn it off.
SKIP_RETRIES = max(0, int(os.environ.get("SKIP_RETRIES") or "5"))
SKIP_RETRY_DELAY = max(0, int(os.environ.get("SKIP_RETRY_DELAY") or "300"))
# `linear` (default): round N waits N x SKIP_RETRY_DELAY. `fixed`: every round
# waits SKIP_RETRY_DELAY, e.g. the cluster job's 5 rounds 300 s apart before
# its single-pod fallback.
SKIP_RETRY_BACKOFF = (
    (os.environ.get("SKIP_RETRY_BACKOFF") or "linear").strip().lower()
)
if SKIP_RETRY_BACKOFF not in ("linear", "fixed"):
    raise ValueError(
        "SKIP_RETRY_BACKOFF must be 'linear' or 'fixed', "
        f"got {SKIP_RETRY_BACKOFF!r}"
    )

# How long a pod can sit in "no SSH endpoint yet" before we surface a hint
# about slow pulls / possible Docker Hub rate limit. Doesn't fail the pod
# — just an informational note in the logs.
STALL_HINT_AFTER = int(os.environ.get("STALL_HINT_AFTER", "180"))
# While SSH probes keep failing identically the probe line is printed once,
# so a long image pull looks like a hang. Print a progress line this often
# (seconds) instead; 0 disables it.
PROBE_HEARTBEAT_SEC = int(os.environ.get("PROBE_HEARTBEAT_SEC", "60"))


# Docker Hub authenticated pulls. Unset means anonymous pulls: fine for
# public images, but Runpod datacenters share an IP pool that hits Docker
# Hub's `toomanyrequests` rate limit fast. Name the credential with
# REGISTRY_AUTH_NAME (looked up in `GET /v2/registries`) or pass its
# REGISTRY_AUTH_ID directly. A name that doesn't resolve is fatal —
# nothing is ever picked implicitly.
#
# REGISTRY_AUTH_ID is reassigned by main() after the name lookup — access
# it via `config.REGISTRY_AUTH_ID` (not a bare `from config import`) to
# pick up the resolved value.
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
    # Runpod base images can still want legacy ssh-rsa for RSA client keys
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

# Lines dropped before LOG_ERROR_PATTERN is applied. Kept to messages that
# are expected by construction, never to a whole daemon: the image ships the
# Slurm a SLURM cluster runs, so every other slurmctld/slurmd error (PMIx
# included) is a finding. A brand-new slurmctld has no saved state, so it
# always logs "Could not open <x> state file" and "NOTE: Trying backup state
# save file" once per state file. slurmd 26.05 logs "Cannot find slurmd
# cpu/memory cgroup" because the platform's slurm.conf enables the cgroup
# plugin and the pod is a cgroup v1 container with no slurmd cgroup to find;
# jobs still run, just without cgroup limits. That is the platform config,
# not the image, so only those two exact lines are dropped. Empty disables
# the filter.
LOG_ERROR_IGNORE = os.environ.get(
    "LOG_ERROR_IGNORE",
    r"^\s*slurmctld: error: (?:Could not open \w+ state file"
    r"|NOTE: Trying backup state save file)"
    r"|^\s*(?:\[[^\]]+\]\s*)?(?:slurmd:\s*)?"
    r"error: Cannot find slurmd (?:cpu|memory) cgroup\s*$",
)

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
# Runpod's authenticated proxy. We just need ANY non-empty value so start.sh
# decides to launch Jupyter (see start.sh: `if [[ $JUPYTER_PASSWORD ]]`).
JUPYTER_TEST_PASSWORD = "admin"

# Jupyter Lab is started in background by start.sh AFTER it prints "Pod is
# ready", so a brief startup grace is needed before we probe.
JUPYTER_WAIT_TIMEOUT = int(os.environ.get("JUPYTER_WAIT_TIMEOUT", "30"))

# Runpod exposes any port declared as `<port>/http` through its public
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
# Instant Clusters (`cluster: true` groups)
# ---------------------------------------------------------------------------

# Clusters bill every node at a premium, so a cluster group refuses to run
# outside RUNPOD_ENV=dev unless this is set: a manifest copied from a dev run
# must not quietly buy prod nodes. CI (base.yml test-pytorch-cluster-instant)
# sets it and runs on prod; local runs opt in the same way.
ALLOW_PROD_CLUSTERS = os.environ.get("ALLOW_PROD_CLUSTERS", "0") == "1"

# When a cluster group finds no Instant Cluster capacity anywhere (it ends
# SKIP after its retries), run the same image as an ordinary one-GPU pod
# group instead, so the image still gets a real test. The pod cannot show
# the multi-node behaviour (head node, Prometheus across nodes, Slurm), and
# the result says so. Candidates come from the per-pod catalog with these
# filters; the cluster group's own `instances:` are cluster GPU ids and are
# not reused. CI sets CLUSTER_POD_FALLBACK=1.
CLUSTER_POD_FALLBACK = os.environ.get("CLUSTER_POD_FALLBACK", "0") == "1"
CLUSTER_POD_FALLBACK_MAX_PRICE = float(
    os.environ.get("CLUSTER_POD_FALLBACK_MAX_PRICE", "1.0") or 1.0
)
CLUSTER_POD_FALLBACK_MIN_VRAM_GB = int(
    os.environ.get("CLUSTER_POD_FALLBACK_MIN_VRAM_GB", "16") or 16
)

DEFAULT_CLUSTER_NODES = 2

# createCluster `type` values, tried in order for each GPU until one is
# created. TRAINING is the console's "Standard cluster": our image on every
# node and nothing else. SLURM ("Slurm cluster") runs the same image with a
# Slurm controller/compute role layered on top; it is the fallback because
# dev has refused TRAINING clusters that it deploys as SLURM. Per group:
# `cluster_types:`; CLUSTER_TYPES (csv) overrides every group.
VALID_CLUSTER_TYPES = ("TRAINING", "SLURM", "APPLICATION", "RAY")
DEFAULT_CLUSTER_TYPES = ("TRAINING", "SLURM")
CLUSTER_TYPES_OVERRIDE = os.environ.get("CLUSTER_TYPES", "")

# Optional csv pinning cluster placement, e.g. `MFS-1`. Empty lets RunPod
# pick any data center with a free node group.
CLUSTER_DATA_CENTER_IDS = os.environ.get("CLUSTER_DATA_CENTER_IDS", "")

# Data centers whose placements are never usable: a cluster that lands there
# is deleted at once and the attempt counts as no capacity. K3S-POC is a dev
# proof-of-concept whose EC2 host is stopped, yet createCluster still places
# L4 clusters on it; the pods report RUNNING and never start.
CLUSTER_EXCLUDE_DATA_CENTERS = os.environ.get(
    "CLUSTER_EXCLUDE_DATA_CENTERS", "K3S-POC",
)

# Per-node hourly price; createCluster's `deployCost` is this times the node
# count. 0 (default) reads the current price from the API; set it only to
# override a price lookup that is wrong or failing.
CLUSTER_DEPLOY_COST = float(os.environ.get("CLUSTER_DEPLOY_COST", "0") or 0)

# How long createCluster may take to materialise every member pod in the
# cluster record. Booting them is then bounded by CLUSTER_BOOT_TIMEOUT.
CLUSTER_PODS_TIMEOUT = int(os.environ.get("CLUSTER_PODS_TIMEOUT", "300"))

# How long a member pod may take to answer SSH (image pull included). Longer
# than CREATE_TIMEOUT because pytorch-cluster is a large image, cluster hosts
# on dev often start with a cold cache, and the cluster has already been paid
# for by the time we wait — giving up early wastes more than waiting does.
CLUSTER_BOOT_TIMEOUT = int(os.environ.get("CLUSTER_BOOT_TIMEOUT", "1500"))

# Grafana's public port on the head node (the auth proxy in front of it —
# see official-templates/pytorch-cluster/config/grafana-proxy).
GRAFANA_PORT = int(os.environ.get("GRAFANA_PORT", "8889"))

# Budget for the head node's monitoring stack to come up and for Prometheus
# to have scraped every node at least once (scrape_interval is 15s).
MONITORING_WAIT_TIMEOUT = int(os.environ.get("MONITORING_WAIT_TIMEOUT", "240"))

# dcgm-exporter needs DCGM support from the GPU and driver; GeForce cards
# (common on dev) may not give it. 0 drops dcgm from the required programs
# and Prometheus jobs — node_exporter still proves the cross-node wiring.
CLUSTER_REQUIRE_DCGM = os.environ.get("CLUSTER_REQUIRE_DCGM", "1") == "1"
GRAFANA_PROXY_TIMEOUT = int(os.environ.get("GRAFANA_PROXY_TIMEOUT", "180"))


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
# let Runpod pick — so we choose the cheapest fitting flavor ourselves.
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
# of Runpod-internal gpuId strings — users only put display names there.
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

# Per-group opt-in for the torchvision/torchaudio/torchcodec part of the
# CUDA check, from the `test_torch_packages:` manifest field.
GROUP_TEST_TORCH_PACKAGES: dict[str, bool] = {}

# Per-group HTTP ports populated from the optional `test_ports:` manifest
# list, as (port, path) pairs. Each port is exposed as `<port>/http` and the
# path (default "/") is probed through the public proxy first (HTTP 200
# required); SSH only diagnoses a proxy failure. A `<port>/<path>` entry lets
# a template hit a dedicated health route, e.g. 80/health.
GROUP_TEST_PORTS: dict[str, list[tuple[int, str]]] = {}

# ComfyUI-specific public-proxy reachability smoke.
GROUP_TEST_COMFYUI: dict[str, bool] = {}

# End-to-end ComfyUI generation test. It implies GROUP_TEST_COMFYUI so the
# public reachability check always runs before model provisioning.
GROUP_TEST_COMFYUI_FUNCTIONAL: dict[str, bool] = {}

# Compatibility-matrix opt-in. Each selected GPU becomes an independent job,
# rather than stopping after the first passing candidate.
GROUP_CHECK_ALL_GPU: dict[str, bool] = {}

# Instant Cluster opt-in, from the `cluster:` manifest field. A cluster group
# provisions a whole cluster per attempt instead of one pod — head node
# (`node-0`) plus workers — and runs the cluster checks (SSH + Jupyter on
# every node, the monitoring stack on the head). Its `instances:` are the
# GPU types to try, in order.
#
#   GROUP_CLUSTER                — the group runs as an Instant Cluster
#   GROUP_CLUSTER_NODES          — pods per cluster (`cluster_nodes`, ≥ 2)
#   GROUP_CLUSTER_GPUS_PER_NODE  — `cluster_gpus_per_node`; 0 picks the
#                                  smallest size the GPU type offers
GROUP_CLUSTER: dict[str, bool] = {}
GROUP_CLUSTER_NODES: dict[str, int] = {}
GROUP_CLUSTER_GPUS_PER_NODE: dict[str, int] = {}
GROUP_CLUSTER_TYPES: dict[str, tuple[str, ...]] = {}

# Image hygiene opt-ins, from the manifest fields of the same name. They
# catch regressions a boot check cannot see: a dependency pin that conflicts
# with something already in the image, a CA upgrade that silently did
# nothing, a vendor base re-introducing a shadowing uv.
#
#   GROUP_TEST_PIP_CHECK    — `pip check` must be clean
#   GROUP_PIP_CHECK_ALLOW   — conflict substrings accepted for that group
#   GROUP_TEST_CA_CERTS     — system trust store carries no revoked root
#   GROUP_MIN_CA_CERTS_VER  — floor for the installed ca-certificates
#   GROUP_TEST_PYTHON_TLS   — certifi bundle carries no revoked root
#   GROUP_REVOKED_CA_NAMES  — per-group override of checks.REVOKED_CA_NAMES
#   GROUP_PYTHON_TLS_VENV   — activate script, for app-owned virtualenvs
#   GROUP_TEST_UV           — exactly one uv, and it resolves
#   GROUP_TEST_VIRTUALENV   — virtualenv works on every shipped interpreter
#   GROUP_TEST_PYTHON_PATH  — only the system python3 sees apt's modules;
#                             python3 is the same interpreter as python
#   GROUP_TEST_AUTORESEARCH — autoresearch train.py runs end to end
#   GROUP_TEST_DCGM_EXPORTER — in-pod dcgm-exporter serves the dashboard labels
#   GROUP_TEST_RAY          — a one-node Ray head runs a GPU task, serves metrics
GROUP_TEST_PIP_CHECK: dict[str, bool] = {}
GROUP_PIP_CHECK_ALLOW: dict[str, list[str]] = {}
GROUP_TEST_CA_CERTS: dict[str, bool] = {}
GROUP_MIN_CA_CERTS_VER: dict[str, str] = {}
GROUP_TEST_PYTHON_TLS: dict[str, bool] = {}
GROUP_REVOKED_CA_NAMES: dict[str, list[str]] = {}
GROUP_PYTHON_TLS_VENV: dict[str, str] = {}
GROUP_TEST_UV: dict[str, bool] = {}
GROUP_TEST_VIRTUALENV: dict[str, bool] = {}
GROUP_TEST_PYTHON_PATH: dict[str, bool] = {}
GROUP_TEST_AUTORESEARCH: dict[str, bool] = {}
GROUP_TEST_DCGM_EXPORTER: dict[str, bool] = {}
GROUP_TEST_RAY: dict[str, bool] = {}
