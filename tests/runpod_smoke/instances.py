"""GPU catalog discovery, instance resolution, and CUDA tag detection.

All the logic that decides "which RunPod instances should this group be
tested on" lives here:

  * discover_gpu_id_map / discover_gpu_catalog — startup-time RunPod queries
  * resolve_gpu_id / is_known_gpu — display-name -> gpuId lookup
  * resolve_instances — apply explicit list / budget filter / exclude filter
  * detect_cuda_version — parse the CUDA version out of an image tag
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import config
from .log import log
from .runpodctl import runpodctl_json


# Extract CUDA version from image tag. Supports both `cuda1281` and
# `cu1281` (interpreted as 12.8.1). Returns "X.Y" suitable for
# --min-cuda-version, or None for images without an embedded CUDA version
# (CPU images, ROCm, NGC). Anchored with \b so we don't match e.g. 'cudnn'.
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


def resolve_gpu_id(display_name: str) -> str:
    """Map a user-supplied GPU display name to its runpodctl gpuId.

    Tries exact match first, then case-insensitive match (so 'RTX 4070 TI'
    in the manifest still finds 'RTX 4070 Ti' in the RunPod catalog).
    Falls back to the raw input — RunPod will then reject it with a clear
    error.
    """
    if display_name in config.GPU_ID_MAP:
        return config.GPU_ID_MAP[display_name]
    lowered = display_name.lower()
    for catalog_name, gpu_id in config.GPU_ID_MAP.items():
        if catalog_name.lower() == lowered:
            return gpu_id
    return display_name


def is_known_gpu(display_name: str) -> bool:
    """Case-insensitive membership check against the discovered GPU catalog."""
    if display_name in config.GPU_ID_MAP:
        return True
    lowered = display_name.lower()
    return any(name.lower() == lowered for name in config.GPU_ID_MAP)


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

    Each entry has: id, displayName, memoryInGb, securePrice,
    communityPrice, manufacturer. Returns [] on any failure (script will
    still work if the manifest uses explicit `instances:` lists)."""
    api_key = _load_runpod_api_key()
    if not api_key:
        return []
    query = ("{ gpuTypes { id displayName memoryInGb "
             "securePrice communityPrice manufacturer } }")
    req = urllib.request.Request(
        "https://api.runpod.io/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # api.runpod.io is fronted by Cloudflare, which rejects the
            # default Python-urllib User-Agent with error code 1010.
            # Identify as a generic client to get through.
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


def _gpu_matches_budget(
    gpu: dict,
    *,
    price_field: str,
    max_price: float,
    min_vram: int,
    manufacturer: str,
) -> Optional[tuple[float, str]]:
    """Return `(price, displayName)` if `gpu` survives the budget filter,
    else None. Single-row predicate so the caller's loop stays flat."""
    price = gpu.get(price_field) or 0
    # price=0 in catalog usually means "not offered in this cloud type" —
    # skip rather than mistakenly treat as free.
    if price <= 0 or price > max_price:
        return None
    if gpu.get("memoryInGb", 0) < min_vram:
        return None
    if manufacturer and (gpu.get("manufacturer") or "").lower() != manufacturer:
        return None
    name = gpu.get("displayName")
    return (float(price), name) if name else None


def _select_by_budget(group_name: str, group_config: dict) -> list[str]:
    """Pick GPUs from `config.GPU_CATALOG` that fit the budget filters,
    sorted cheapest-first. Returns [] (and logs a warn) when the catalog
    is empty — typically when `RUNPOD_API_KEY` isn't set."""
    if not config.GPU_CATALOG:
        log(
            f"warn: group '{group_name}' uses max_price_per_hour but the "
            "GPU catalog (with prices) is empty — set RUNPOD_API_KEY or use "
            "an explicit instances: list",
        )
        return []

    price_field = (
        "communityPrice" if config.CLOUD_TYPE.upper() == "COMMUNITY"
        else "securePrice"
    )
    max_price = float(group_config["max_price_per_hour"])
    min_vram = int(group_config.get("min_vram_gb", 0))
    manufacturer = (group_config.get("manufacturer") or "").lower()

    matches = (
        _gpu_matches_budget(
            gpu,
            price_field=price_field,
            max_price=max_price,
            min_vram=min_vram,
            manufacturer=manufacturer,
        )
        for gpu in config.GPU_CATALOG
    )
    candidates = sorted((m for m in matches if m is not None), key=lambda x: x[0])
    return [name for _, name in candidates]


def resolve_instances(group_name: str, group_config: dict) -> list[str]:
    """Decide which GPU display names this group should try, in order.

    Priority:
      0. CPU groups (name == 'base_cpu') — runpodctl 2.3.0 can't pick a
         specific CPU flavor by name, so we expand to one entry per
         `config.CPU_FLAVORS` label. Each label is a `(vcpu, mem)` ask
         that steers RunPod's scheduler into a different flavor pool
         (see config.py for rationale). The caller's per-instance loop
         then walks them in order on UNAVAILABLE / STUCK, identical to
         how it cycles through GPU types.
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
        return list(config.CPU_FLAVORS.keys())

    exclude_patterns = list(group_config.get("exclude_instances") or [])

    explicit = group_config.get("instances") or []
    if explicit:
        names = list(explicit)
    elif group_config.get("max_price_per_hour") is not None:
        names = _select_by_budget(group_name, group_config)
    else:
        return []

    return _apply_exclude_filter(names, exclude_patterns, group_name=group_name)
