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
import re
from typing import Optional

from . import api, config
from .log import log
from .manifest import _normalize_bool


# Supports `cuda1281` / `cu1300` and the ComfyUI `cuda13.0` convention.
CUDA_TAG_RE = re.compile(
    r"\bcu(?:da)?(\d{2})(?:(\d)(\d)|\.(\d))\b",
    re.IGNORECASE,
)


def detect_cuda_version(image: str) -> Optional[str]:
    """Parse a CUDA version like '12.8' from an image tag.

    Examples:
        runpod/base:...-cuda1281-ubuntu2204     -> '12.8'
        runpod/pytorch:...-cu1300-torch290-...  -> '13.0'
        runpod/comfyui:cuda13.0                 -> '13.0'
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
    major = m.group(1)
    minor = m.group(2) or m.group(4)
    return f"{int(major)}.{int(minor)}"


def resolve_gpu_id(display_name: str) -> str:
    """Map a user-supplied GPU display name to its RunPod gpu id.

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


def discover_gpu_catalog() -> list[dict]:
    """Fetch GPU types from `GET /v2/catalog/gpus`.

    Entries keep the field names the rest of the module already uses
    (`displayName`, `memoryInGb`, `securePrice`, `communityPrice`) so the
    budget/vRAM filters didn't have to change; `cudaVersions` is new and
    carries per-version capacity, which is what makes a GPU x CUDA sweep
    possible without blind pod-create attempts.

    `include=AVAILABILITY` needs `product`, and scopes availability and
    lowest-price to that context. Returns [] on any failure — the script
    still works if the manifest uses explicit `instances:` lists.
    """
    status, data = api.request_with_retries(
        "GET",
        "/catalog/gpus",
        params={
            "include": ["AVAILABILITY"],
            "product": ["POD"],
            "cloud": config.CLOUD_TYPE.upper(),
            "count": 1,
        },
        timeout=30,
    )
    if not (200 <= status < 300) or not isinstance(data, dict):
        api.log_error("warn: could not fetch GPU catalog", status, data, indent=0)
        return []
    out: list[dict] = []
    for gpu in data.get("gpus") or []:
        if not isinstance(gpu, dict):
            continue
        price = gpu.get("price") or {}
        cuda = [
            cv.get("version")
            for cv in (gpu.get("cudaVersions") or [])
            if isinstance(cv, dict) and cv.get("version")
        ]
        cuda_available = [
            cv.get("version")
            for cv in (gpu.get("cudaVersions") or [])
            if isinstance(cv, dict) and cv.get("version") and cv.get("available")
        ]
        out.append({
            "id": gpu.get("id") or "",
            "displayName": gpu.get("name") or "",
            "memoryInGb": gpu.get("memory") or 0,
            "manufacturer": gpu.get("manufacturer") or "",
            "securePrice": price.get("secure") or 0,
            "communityPrice": price.get("community") or 0,
            "availability": gpu.get("availability") or "",
            "cudaVersions": cuda,
            "cudaVersionsAvailable": cuda_available,
        })
    return out


def discover_gpu_id_map() -> dict[str, str]:
    """Build {displayName: gpuId} from the already-fetched catalog.

    Falls back to its own request when called before the catalog is loaded,
    so callers don't have to care about ordering.
    """
    catalog = config.GPU_CATALOG or discover_gpu_catalog()
    return {
        gpu["displayName"]: gpu["id"]
        for gpu in catalog
        if gpu.get("displayName") and gpu.get("id")
    }


def cuda_versions_offered(display_name: str, *, only_available: bool = True) -> list[str]:
    """CUDA versions the catalog reports for one GPU display name.

    `only_available` keeps just the versions with free capacity right now —
    the field the API describes as "at least one machine on this CUDA version
    has free capacity". Pinning a version nobody reports yields a capacity
    error rather than a fallback, so filtering here is what keeps a GPU x
    CUDA sweep from being mostly wasted attempts.
    """
    key = "cudaVersionsAvailable" if only_available else "cudaVersions"
    lowered = display_name.lower()
    for gpu in config.GPU_CATALOG:
        if (gpu.get("displayName") or "").lower() == lowered:
            return list(gpu.get(key) or [])
    return []


def cuda_axis_for(group: str, display_name: str) -> list[str]:
    """Versions to test `display_name` on for `group`, newest first.

    [] means "no CUDA axis for this group" — the caller then emits a single
    unpinned job and the floor is derived from the image tag as before.
    """
    all_mode = config.GROUP_CUDA_ALL.get(group, False)
    requested = config.GROUP_CUDA_VERSIONS.get(group) or []
    if not (all_mode or requested):
        return []
    offered = cuda_versions_offered(display_name)
    if all_mode:
        picked = offered
    else:
        picked = [v for v in requested if v in offered]
    return sorted(picked, key=_version_key, reverse=True)


def _version_key(version: str) -> tuple:
    try:
        return tuple(int(p) for p in version.split("."))
    except (TypeError, ValueError):
        return (0,)


def discover_cpu_catalog() -> list[dict]:
    """Fetch CPU flavors from `GET /v2/catalog/cpus`.

    Needed because v2 requires an explicit `cpu.id` + `vcpuCount` on pod
    create, where the old CLI let RunPod pick the flavor itself.
    """
    status, data = api.request_with_retries(
        "GET",
        "/catalog/cpus",
        params={
            "include": ["AVAILABILITY"],
            "product": ["POD"],
        },
        timeout=30,
    )
    if not (200 <= status < 300) or not isinstance(data, dict):
        api.log_error("warn: could not fetch CPU catalog", status, data, indent=0)
        return []
    return [c for c in (data.get("cpus") or []) if isinstance(c, dict)]


# Availability is a point-in-time snapshot, so it ORDERS candidates rather
# than excluding them: at the time of writing every CPU flavor reports NONE,
# and refusing to try would mean never creating a CPU pod at all. A create
# against a full pool comes back UNAVAILABLE, which the runner already
# handles by moving to the next candidate.
_AVAILABILITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}


def pick_cpu_flavor() -> tuple[str, int]:
    """Choose (flavor_id, vcpuCount) for a CPU pod.

    `CPU_FLAVOR_ID` wins when set. Otherwise the flavor whose `vcpu` range
    admits `config.CPU_VCPU_COUNT`, preferring better-reported availability
    and then the lower `price.securePerVcpu`. Returns ("", 0) only when the
    catalog is unreachable or no flavor supports the requested vCPU count.
    """
    catalog = config.CPU_CATALOG or discover_cpu_catalog()
    if catalog and not config.CPU_CATALOG:
        config.CPU_CATALOG.extend(catalog)
    want = config.CPU_VCPU_COUNT

    if config.CPU_FLAVOR_ID:
        # Trust the override even if it isn't in the catalog — the API is
        # the authority and a stale catalog shouldn't block an explicit ask.
        return config.CPU_FLAVOR_ID, want

    def fits(flavor: dict) -> bool:
        vcpu = flavor.get("vcpu") or {}
        lo = int(vcpu.get("min") or 0)
        hi = int(vcpu.get("max") or 0)
        return bool(flavor.get("id")) and lo <= want <= (hi or want)

    candidates = [f for f in catalog if fits(f)]
    if not candidates:
        return "", 0
    best = min(
        candidates,
        key=lambda f: (
            _AVAILABILITY_RANK.get(f.get("availability") or "", 1),
            float((f.get("price") or {}).get("securePerVcpu") or 1e9),
        ),
    )
    return best.get("id") or "", want


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


def _select_all_gpus(group_name: str, group_config: dict) -> list[str]:
    """Return every catalog GPU matching optional vRAM/vendor filters."""
    if not config.GPU_CATALOG:
        log(
            f"warn: group '{group_name}' uses check_all_gpu but the "
            "GPU catalog is empty — set RUNPOD_API_KEY or use explicit "
            "instances"
        )
        return []
    min_vram = int(group_config.get("min_vram_gb", 0))
    manufacturer = (group_config.get("manufacturer") or "").lower()
    names = [
        gpu["displayName"]
        for gpu in config.GPU_CATALOG
        if gpu.get("displayName")
        and gpu.get("memoryInGb", 0) >= min_vram
        and (
            not manufacturer
            or (gpu.get("manufacturer") or "").lower() == manufacturer
        )
    ]
    return sorted(set(names))


def resolve_instances(group_name: str, group_config: dict) -> list[str]:
    """Decide which GPU display names this group should try, in order.

    Priority:
      0. CPU groups (name in `config.CPU_GROUP_NAMES`) — expand to one
         entry per `config.CPU_CANDIDATES` label. The flavor comes from
         `pick_cpu_flavor`; the labels vary only placement (SECURE vs
         COMMUNITY, optional data centres). The caller's per-instance loop
         walks them in order on UNAVAILABLE / STUCK, identical to how it
         cycles through GPU types.
      1. Explicit `instances:` list in the manifest — wins, used as-is.
      2. `max_price_per_hour: X` (+ optional `min_vram_gb`, `manufacturer`)
         — auto-pick from RunPod catalog, sorted cheapest first.
      3. `check_all_gpu: true` — every catalog GPU matching the optional
         vRAM/vendor filters, for compatibility-matrix runs.

    After candidate selection, an optional `exclude_instances:` list of
    fnmatch-style patterns is subtracted. Use this to block known-bad
    matches like Blackwell GPUs on PyTorch 2.6 builds (no sm_120 kernels):

        pytorch:
            max_price_per_hour: 1.0
            exclude_instances:
            - "*Blackwell*"

    Returns [] when neither is set (caller will SKIP the group).
    """
    if group_name in config.CPU_GROUP_NAMES:
        return list(config.CPU_CANDIDATES.keys())

    exclude_patterns = list(group_config.get("exclude_instances") or [])

    explicit = group_config.get("instances") or []
    if explicit:
        names = list(explicit)
    elif group_config.get("max_price_per_hour") is not None:
        names = _select_by_budget(group_name, group_config)
    elif _normalize_bool(group_config.get("check_all_gpu")):
        names = _select_all_gpus(group_name, group_config)
    else:
        return []

    return _apply_exclude_filter(names, exclude_patterns, group_name=group_name)
