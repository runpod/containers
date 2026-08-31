#!/usr/bin/env python3
"""Smoke-test RunPod container images.

Entry point. See ./README.md for the manifest schema, env vars, and how
the CUDA / Jupyter checks work. All implementation lives in the
runpod_smoke/ package next to this file.

Usage:
    ./test_images.py [path/to/images.yaml] [group_filter]

Requirements: a RunPod API key (RUNPOD_API_KEY or ~/.runpod/config.toml),
python3 >= 3.9
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# When invoked via a symlink (we keep one at /tmp/runpod-scripts/testing/),
# Python puts the symlink's directory on sys.path, NOT the directory that
# actually contains the `runpod_smoke/` package. Resolve the real path so
# our package imports work regardless of how the script was launched.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from runpod_smoke import api, config
from runpod_smoke.instances import (
    cuda_axis_for,
    cuda_versions_offered,
    discover_gpu_catalog,
    discover_gpu_id_map,
    is_known_gpu,
    resolve_instances,
)
from runpod_smoke.log import ensure_worker_tag, log
from runpod_smoke.manifest import (
    _normalize_bool,
    _normalize_cuda_version,
    parse_manifest,
)
from runpod_smoke.pod import discover_registry_auth
from runpod_smoke.runner import test_image


# Each entry: (image, group, instances-to-try, cuda_pin). One pod is created
# per entry; the runner iterates instances internally until something
# settles. `cuda_pin` is "" unless the group has a CUDA axis.
Job = tuple[str, str, list[str], str]

# Per-attempt outcome:
#   (image, status, note, instance_used, host_cuda, requested_cuda)
# `requested_cuda` is the pinned version, kept separately so a SKIPped
# attempt still says WHICH cell of the matrix it belongs to. A list avoids
# overwriting rows when one GPU produces several jobs.
Result = tuple[str, str, str, str, str, str]


# ---------------------------------------------------------------------------
# CLI / preflight
# ---------------------------------------------------------------------------


def _parse_args() -> tuple[Path, Optional[str]]:
    """argv → (manifest_path, optional group filter). No validation here
    — that's `_check_prereqs`'s job."""
    images_path = Path(sys.argv[1] if len(sys.argv) > 1 else "images")
    group_filter = sys.argv[2] if len(sys.argv) > 2 else None
    return images_path, group_filter


def _check_prereqs(manifest_path: Path) -> Optional[int]:
    """Return None on success, or an exit-code int on failure. Verifies:
      1. the manifest file actually exists
      2. the REST API v2 accepts our key
    Anything else (GPU catalog, registry auth) is best-effort — the script
    degrades gracefully if those are missing."""
    if not manifest_path.is_file():
        log(f"Images manifest not found: {manifest_path}")
        return 1
    ok, detail = api.api_available()
    if not ok:
        log(detail)
        return 1
    return None


# ---------------------------------------------------------------------------
# Runtime-state initialization (GPU map + catalog + registry auth)
# ---------------------------------------------------------------------------


def _init_gpu_catalog() -> None:
    # One request now serves both the id map and the price/vRAM filters.
    config.GPU_CATALOG.extend(discover_gpu_catalog())
    config.GPU_ID_MAP.update(discover_gpu_id_map())
    if config.GPU_CATALOG:
        with_cuda = sum(1 for g in config.GPU_CATALOG if g.get("cudaVersions"))
        log(
            f"loaded {len(config.GPU_CATALOG)} GPU types from "
            f"GET /v2/catalog/gpus ({with_cuda} reporting CUDA availability)"
        )
    else:
        log(
            "warn: no GPU catalog — budget-based instance selection "
            "(max_price_per_hour) will be disabled. Set RUNPOD_API_KEY or "
            "ensure ~/.runpod/config.toml has 'apikey'."
        )


def _init_registry_auth() -> None:
    if not config.REGISTRY_AUTH_ID:
        config.REGISTRY_AUTH_ID = (
            discover_registry_auth(config.REGISTRY_AUTH_NAME) or ""
        )
    if config.REGISTRY_AUTH_ID:
        log(f"using registry auth: {config.REGISTRY_AUTH_ID}")
    else:
        log(
            "warn: no registry auth configured — Docker Hub pulls will be "
            "anonymous and likely hit the toomanyrequests rate limit"
        )


# ---------------------------------------------------------------------------
# Manifest derivatives (per-group lookup dicts) + instance resolution
# ---------------------------------------------------------------------------


def _coerce_ports(raw_ports: object, group: str) -> list[int]:
    """Coerce optional `test_ports` list entries to valid TCP port numbers."""
    if not isinstance(raw_ports, list):
        return []
    ports: list[int] = []
    for entry in raw_ports:
        try:
            port = int(str(entry).strip())
        except (TypeError, ValueError):
            log(
                f"warn: group '{group}': test_ports entry {entry!r} "
                "is not a valid TCP port — skipping"
            )
            continue
        if 1 <= port <= 65535:
            ports.append(port)
        else:
            log(
                f"warn: group '{group}': test_ports entry {entry!r} "
                "is outside 1–65535 — skipping"
            )
    return ports


def _apply_cuda_axis(group: str, raw: object) -> None:
    """Read the `cuda_versions:` manifest field for one group.

    Accepts the literal `all` (every version the GPU reports capacity for)
    or a list of exact X.Y versions. Enabling it turns each candidate GPU
    into one job per version and pins the host with
    `gpu.allowedCudaVersions`, which the API matches exactly — so a
    `min_cuda_version` floor on the same group would be both redundant and
    rejected, and is dropped here.
    """
    if raw is None or raw == "":
        return
    entries = raw if isinstance(raw, list) else [raw]
    wants_all = any(str(e).strip().strip('"\'').lower() == "all" for e in entries)
    versions: list[str] = []
    if not wants_all:
        for entry in entries:
            normalized = _normalize_cuda_version(entry)
            if normalized:
                versions.append(normalized)
            else:
                log(
                    f"warn: group '{group}': cuda_versions entry {entry!r} "
                    "is not an X.Y version — skipping"
                )
    if not (wants_all or versions):
        return
    if wants_all:
        config.GROUP_CUDA_ALL[group] = True
        log(
            f"group '{group}': cuda_versions=all (one job per GPU x every "
            "CUDA version that GPU reports capacity for)"
        )
    else:
        config.GROUP_CUDA_VERSIONS[group] = versions
        log(
            f"group '{group}': cuda_versions={versions} "
            "(pinned via gpu.allowedCudaVersions, exact match)"
        )
    if config.GROUP_MIN_CUDA.pop(group, None):
        log(
            f"group '{group}': dropped min_cuda_version — a CUDA axis pins "
            "exact versions and the API rejects both fields together",
            indent=1,
        )


def _apply_manifest_overrides(manifest: dict[str, dict]) -> None:
    """Populate the per-group dicts on `config` that `pod.create_pod` and
    `runner.test_pair` consult at run-time: `GROUP_MIN_CUDA` (fallback
    CUDA version for tag-less images like NGC `nvidia-pytorch:25.11`)
    `GROUP_TEST_JUPYTER` (opt-in for the Jupyter probes), and
    `GROUP_TEST_PORTS` (generic public HTTP service probes),
    `GROUP_CHECK_ALL_GPU` (one independent job per matching GPU), and the
    ComfyUI reachability / functional-generation opt-ins."""
    for grp, contents in manifest.items():
        normalized = _normalize_cuda_version(contents.get("min_cuda_version"))
        if normalized:
            config.GROUP_MIN_CUDA[grp] = normalized
            log(
                f"group '{grp}': min_cuda_version={normalized} "
                "(applied when image tag has no embedded CUDA)"
            )
    for grp, contents in manifest.items():
        if _normalize_bool(contents.get("test_jupyter")):
            config.GROUP_TEST_JUPYTER[grp] = True
            # JUPYTER_TEST_PASSWORD is a hard-coded throw-away token for
            # short-lived test pods (see config.py), but we still redact
            # it in logs so the pattern stays clean for CodeQL and any
            # future operator who copy-pastes the log into a ticket.
            log(
                f"group '{grp}': test_jupyter=true "
                "(JUPYTER_PASSWORD=<redacted>, expose 8888/http)"
            )
    for grp, contents in manifest.items():
        ports = _coerce_ports(contents.get("test_ports"), grp)
        if ports:
            config.GROUP_TEST_PORTS[grp] = ports
            log(
                f"group '{grp}': test_ports={ports} "
                "(expose as <port>/http, probe public proxy first)"
            )
    for grp, contents in manifest.items():
        _apply_cuda_axis(grp, contents.get("cuda_versions"))
    for grp, contents in manifest.items():
        if _normalize_bool(contents.get("check_all_gpu")):
            config.GROUP_CHECK_ALL_GPU[grp] = True
            log(
                f"group '{grp}': check_all_gpu=true "
                "(one independent smoke job per resolved GPU)"
            )
        reach = _normalize_bool(contents.get("test_comfyui"))
        functional = _normalize_bool(contents.get("test_comfyui_functional"))
        if functional:
            config.GROUP_TEST_COMFYUI_FUNCTIONAL[grp] = True
            log(
                f"group '{grp}': test_comfyui_functional=true "
                "(provision model, run workflow, validate PNG)"
            )
        if reach or functional:
            config.GROUP_TEST_COMFYUI[grp] = True
            log(
                f"group '{grp}': test_comfyui=true "
                f"(proxy-first reachability on :{config.COMFYUI_PORT})"
            )


def _resolve_all_instances(manifest: dict[str, dict]) -> dict[str, list[str]]:
    """Per-group instance lookup — done up-front so we can warn about
    typos / empty lists once, instead of per-job."""
    return {grp: resolve_instances(grp, contents)
            for grp, contents in manifest.items()}


def _warn_unknown_instances(resolved: dict[str, list[str]]) -> None:
    """Surface manifest entries that don't map to any RunPod display name
    (typos / casing) so the user sees them once at startup instead of
    inside the per-job logs."""
    unmapped = sorted({
        inst
        for instances in resolved.values()
        for inst in instances
        if not config.is_cpu_instance(inst) and not is_known_gpu(inst)
    })
    if not unmapped:
        return
    log(
        f"warn: {len(unmapped)} instance(s) don't match any RunPod "
        "displayName — check spelling/casing:"
    )
    for inst in unmapped:
        log(f"  - {inst!r}", indent=1)


def _log_budget_picks(
    manifest: dict[str, dict],
    resolved: dict[str, list[str]],
) -> None:
    """For each budget-mode group, log what the catalog filter picked.
    Particularly useful when the user wrote `max_price_per_hour: X` and
    wants to see which GPUs cleared the threshold."""
    for grp, instances in resolved.items():
        contents = manifest[grp]
        if "max_price_per_hour" not in contents or contents.get("instances"):
            continue
        budget = contents["max_price_per_hour"]
        preview = ", ".join(instances[:8]) + (
            f", ... (+{len(instances) - 8} more)" if len(instances) > 8 else ""
        )
        log(
            f"group '{grp}': budget ≤ ${budget}/hr → {len(instances)} "
            f"candidate(s): {preview or '(none — no GPU fits)'}"
        )


# ---------------------------------------------------------------------------
# Job fan-out
# ---------------------------------------------------------------------------


def _build_jobs(
    manifest: dict[str, dict],
    resolved: dict[str, list[str]],
    group_filter: Optional[str],
    results: list[Result],
) -> list[Job]:
    """Flatten the manifest into a list of `(image, group, instances)`
    jobs that can run independently. Groups with no resolvable instances
    are recorded directly into `results` as SKIPs (caller handles the
    summary print)."""
    jobs: list[Job] = []
    for group, contents in manifest.items():
        if group_filter and group != group_filter:
            continue
        instances = resolved.get(group, [])
        if not instances:
            log(
                f"skipping group '{group}': no instances resolved "
                "(none of 'instances:', 'max_price_per_hour:' or "
                "'check_all_gpu:' produced candidates)"
            )
            for img in contents.get("images", []):
                results.append((img, "SKIP", "no instances configured", "", "", ""))
            continue
        check_all = config.GROUP_CHECK_ALL_GPU.get(group, False)
        cuda_axis = bool(
            config.GROUP_CUDA_ALL.get(group)
            or config.GROUP_CUDA_VERSIONS.get(group)
        )
        for img in contents.get("images", []):
            if cuda_axis and check_all:
                jobs.extend(_cuda_matrix_jobs(img, group, instances, results))
            elif cuda_axis:
                jobs.extend(_cuda_per_version_jobs(img, group, instances))
            elif check_all:
                jobs.extend((img, group, [inst], "") for inst in instances)
            else:
                jobs.append((img, group, instances, ""))
    return _cap_jobs(jobs)


def _cuda_matrix_jobs(
    image: str, group: str, instances: list[str], results: list[Result],
) -> list[Job]:
    """One job per (GPU, CUDA version) — the full matrix, for check_all_gpu.

    Versions with no free capacity are dropped rather than attempted: the
    API matches `allowedCudaVersions` exactly and answers a full pool with a
    capacity error, so trying them would just buy SKIP rows. A GPU that
    reports nothing usable is recorded as a SKIP so it still shows up in the
    matrix instead of vanishing.
    """
    jobs: list[Job] = []
    for inst in instances:
        versions = cuda_axis_for(group, inst)
        if not versions:
            offered = cuda_versions_offered(inst, only_available=False)
            detail = (
                f"offers {', '.join(offered)} but none had capacity"
                if offered else "reports no CUDA versions"
            )
            # No version reached a pod-create, so requested_cuda stays empty
            # and the pivot shows this GPU as an all-dots row. The note has
            # to carry the scope, since the CUDA column has nothing to show.
            results.append((
                image, "SKIP",
                f"GPU not covered: {detail}",
                inst, "", "",
            ))
            continue
        jobs.extend((image, group, [inst], v) for v in versions)
    return jobs


def _cuda_per_version_jobs(
    image: str, group: str, instances: list[str],
) -> list[Job]:
    """One job per CUDA version, each keeping the full candidate list.

    Without `check_all_gpu` the contract is "try candidates until one
    passes", and adding a CUDA axis shouldn't silently turn that into a
    full product — that would multiply a budget-filtered pool of ~20 cards
    into ~40 pods. So each version gets one job whose candidates are the
    GPUs that actually offer it, and the runner short-circuits on the first
    PASS exactly as it does without the axis.
    """
    per_version: dict[str, list[str]] = {}
    for inst in instances:
        for version in cuda_axis_for(group, inst):
            per_version.setdefault(version, []).append(inst)
    return [
        (image, group, candidates, version)
        for version, candidates in sorted(per_version.items(), reverse=True)
    ]


def _warn_unviable_cuda_axis(
    manifest: dict[str, dict], resolved: dict[str, list[str]],
) -> None:
    """Warn when a CUDA axis could never have produced a single job.

    Runs before any pod is created. Without this the run is silent: every
    GPU turns into a SKIP row, `ON_SKIP=pass` keeps the job green, and a
    sweep that tested nothing looks the same as one that passed.

    Only misconfiguration is reported. "Versions exist and match, but none
    has capacity right now" is transient, already visible as per-GPU SKIP
    rows, and would fire on healthy runs — so it stays silent here.
    """
    for group in manifest:
        candidates = resolved.get(group, [])
        if not candidates:
            continue
        all_mode = config.GROUP_CUDA_ALL.get(group, False)
        requested = config.GROUP_CUDA_VERSIONS.get(group) or []
        if not (all_mode or requested):
            continue
        offered: set[str] = set()
        for inst in candidates:
            offered |= set(cuda_versions_offered(inst, only_available=False))
        if not offered:
            log(
                f"::warning::group '{group}': cuda_versions is set but none "
                f"of the {len(candidates)} candidate GPUs reports any CUDA "
                "version, so no pod can be created. The axis only applies "
                "to NVIDIA — drop cuda_versions for a ROCm/AMD sweep."
            )
        elif requested and not set(requested) & offered:
            log(
                f"::warning::group '{group}': cuda_versions="
                f"{sorted(requested)} but the candidate GPUs only offer "
                f"{sorted(offered)}, so nothing will be tested."
            )


def _cap_jobs(jobs: list[Job]) -> list[Job]:
    """Enforce MAX_CUDA_COMBOS so a stray sweep can't run for a day."""
    if len(jobs) <= config.MAX_CUDA_COMBOS:
        return jobs
    log(
        f"warn: {len(jobs)} jobs exceeds MAX_CUDA_COMBOS="
        f"{config.MAX_CUDA_COMBOS} — dropping the last "
        f"{len(jobs) - config.MAX_CUDA_COMBOS}. Narrow the sweep with "
        "min-vram-gb / exclude-instances, or raise the cap deliberately."
    )
    return jobs[:config.MAX_CUDA_COMBOS]


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


def _run_jobs_serial(jobs: list[Job], results: list[Result]) -> None:
    """Single-threaded run — no worker tags, simpler logs, group-header
    banner each time the group changes."""
    current_group: Optional[str] = None
    for img, group, instances, cuda_pin in jobs:
        if group != current_group:
            print()
            log(f"---------- group: {group} ----------")
            current_group = group
        status, note, instance, host_cuda = test_image(
            img, instances, group, cuda_pin
        )
        results.append((img, status, note, instance, host_cuda, cuda_pin))


def _run_one_tagged_job(job: Job) -> Result:
    """ThreadPool worker. The W<N> tag is assigned to the THREAD (not the
    job), so e.g. with 5 jobs and 3 workers you still see only W1/W2/W3,
    each handling 1-2 jobs sequentially."""
    img, grp, insts, cuda_pin = job
    ensure_worker_tag()
    pin_note = f" cuda={cuda_pin}" if cuda_pin else ""
    log(f"start [group={grp}] image={img}{pin_note}")
    status, note, instance, host_cuda = test_image(img, insts, grp, cuda_pin)
    log(f"done  [group={grp}] image={img}{pin_note} -> {status}")
    return img, status, note, instance, host_cuda, cuda_pin


def _run_jobs_parallel(jobs: list[Job], results: list[Result]) -> None:
    """ThreadPool fan-out capped at MAX_PARALLEL. Each worker holds at
    most one pod at a time."""
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL) as pool:
        futures = [pool.submit(_run_one_tagged_job, job) for job in jobs]
        for fut in as_completed(futures):
            results.append(fut.result())


def _run_jobs(jobs: list[Job], results: list[Result]) -> None:
    if not jobs:
        log("no jobs to run after filtering")
        return
    print()
    log(
        f"==================== running {len(jobs)} job(s) "
        f"with MAX_PARALLEL={config.MAX_PARALLEL} ===================="
    )
    if config.MAX_PARALLEL <= 1:
        _run_jobs_serial(jobs, results)
    else:
        _run_jobs_parallel(jobs, results)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _format_result_line(want: str, img: str, status: str, note: str,
                        instance: str, host_cuda: str = "") -> Optional[str]:
    """Format one row of the summary, or None when this result doesn't
    belong in the `want` bucket. CPU labels ('cpu-secure', 'cpu-community',
    …) are already human-readable, so they go to the summary verbatim.

    `host_cuda` is the CUDA version the pod actually ran on — reported because
    the image tag only sets a floor, so the tag alone doesn't tell you what
    the run proved."""
    if status != want:
        return None
    label = f"{instance} - CUDA {host_cuda}" if instance and host_cuda else instance
    inst_str = f" [{label}]" if label else ""
    note_str = f" -- {note}" if note else ""
    return f"  {want:6s} {img}{inst_str}{note_str}"


_STATUS_ICON = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIP": "⚠️ SKIP"}


def _md_cell(value: str) -> str:
    """Escape a value for a markdown table cell."""
    return (value or "").replace("|", "\\|").replace("\n", " ") or "—"


_CELL_ICON = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️"}


def _emit_cuda_pivot(results: list[Result]) -> list[str]:
    """GPU-by-CUDA pivot table, or [] when no CUDA axis was requested.

    A flat list is unreadable at 30+ rows, and the whole point of the axis
    is comparing one GPU across versions — so rows are GPUs, columns are
    CUDA versions.

    Every resolved GPU gets a row, including ones where no version had
    capacity and no pod was ever created. Those come out as a full row of
    `·`, which is the honest answer: "not covered". Leaving them out would
    make an untested GPU indistinguishable from one that doesn't exist.
    """
    attempted = [r for r in results if r[5]]
    if not attempted:
        return []
    versions = sorted(
        {r[5] for r in attempted},
        key=lambda v: tuple(int(p) for p in v.split(".")) if "." in v else (0,),
    )
    # A comma in the label means a multi-candidate SKIP, which can't be a
    # single row — the axis produces one instance per job, so this only
    # guards against a non-axis group sneaking into the same run.
    gpus = sorted({r[3] for r in results if r[3] and ", " not in r[3]})
    cell: dict[tuple[str, str], str] = {}
    for _img, status, _note, inst, _host, req in attempted:
        cell[(inst, req)] = _CELL_ICON.get(status, status)
    out = ["", "### GPU x CUDA", ""]
    out.append("| GPU | " + " | ".join(f"CUDA {v}" for v in versions) + " |")
    out.append("|" + "|".join(["---"] * (len(versions) + 1)) + "|")
    for gpu in gpus:
        cells = [cell.get((gpu, v), "·") for v in versions]
        out.append(f"| {_md_cell(gpu)} | " + " | ".join(cells) + " |")
    out += [
        "",
        "✅ pass · ❌ fail · ⚠️ skip (pod attempted, no capacity) · "
        "· not attempted (no capacity at planning time)",
        "",
    ]
    return out


def _emit_step_summary(results: list[Result], counts: dict[str, int]) -> None:
    """Append the matrix to $GITHUB_STEP_SUMMARY as a markdown table.

    The stdout matrix is only reachable by downloading the job log, which
    needs repo admin. The step summary renders on the run page for anyone.
    No-op outside Actions; never fatal.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    images = {r[0] for r in results}
    single = next(iter(images)) if len(images) == 1 else ""
    head = ["Status", "Instance", "CUDA", "Note"]
    if not single:
        head.insert(1, "Image")
    lines = [
        "## Smoke-test matrix",
        "",
        f"**{counts['PASS']} PASS · {counts['FAIL']} FAIL · {counts['SKIP']} SKIP**",
        "",
    ]
    if single:
        lines += [f"Image: `{single}`", ""]
    lines += _emit_cuda_pivot(results)
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for want in ("FAIL", "SKIP", "PASS"):
        for img, status, note, instance, host_cuda, req_cuda in results:
            if status != want:
                continue
            row = [
                _STATUS_ICON.get(status, status),
                _md_cell(instance),
                _md_cell(host_cuda or req_cuda),
                _md_cell(note),
            ]
            if not single:
                row.insert(1, f"`{img}`")
            lines.append("| " + " | ".join(row) + " |")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        log(f"warn: could not write step summary: {exc}")


def _write_results_json(results: list[Result], counts: dict[str, int]) -> None:
    """Write the matrix to $SMOKE_RESULTS_JSON so CI can keep it as an
    artifact and diff runs against each other. No-op when unset."""
    path = os.environ.get("SMOKE_RESULTS_JSON")
    if not path:
        return
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": {k: counts[k] for k in ("PASS", "FAIL", "SKIP")},
        "results": [
            {
                "image": img,
                "status": status,
                "instance": instance,
                "cuda": host_cuda,
                "requested_cuda": req_cuda,
                "note": note,
            }
            for img, status, note, instance, host_cuda, req_cuda in results
        ],
    }
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log(f"wrote results JSON -> {path}")
    except OSError as exc:
        log(f"warn: could not write results JSON: {exc}")


def _print_summary(results: list[Result]) -> int:
    """Print the SUMMARY block and return the exit code.

    FAIL is ALWAYS fatal (exit 1) — a broken container is never something
    we want to slip past CI.

    For SKIPs (test never actually ran against the image) the behaviour
    is driven by `config.ON_SKIP`:
      'fail' (default) → exit 1 + `::error::` GitHub annotation
      'warn'           → exit 0 + `::warning::` GitHub annotation
                         (job stays green but the run shows a yellow
                         warning bubble in the PR check tab — useful when
                         capacity-shortage shouldn't block PRs but you
                         still want a visible signal)
      'pass'           → exit 0, no annotation (legacy lenient mode)

    A run with BOTH FAIL and SKIP exits 1 with the FAIL annotation; the
    SKIP count is already visible in the totals line so we don't double-
    annotate."""
    print()
    print("=" * 84)
    print(" SUMMARY ".center(84, "="))
    print("=" * 84)
    counts: dict[str, int] = defaultdict(int)
    for _img, status, _note, _instance, _host_cuda, _req in results:
        counts[status] += 1
    print(
        f"totals: {counts['PASS']} PASS, "
        f"{counts['FAIL']} FAIL, "
        f"{counts['SKIP']} SKIP\n"
    )
    for want in ("FAIL", "SKIP", "PASS"):
        for img, status, note, instance, host_cuda, req_cuda in results:
            line = _format_result_line(
                want, img, status, note, instance, host_cuda or req_cuda
            )
            if line is not None:
                print(line)

    _emit_step_summary(results, counts)
    _write_results_json(results, counts)

    if counts["FAIL"] > 0:
        return 1
    if counts["SKIP"] == 0 or config.ON_SKIP == "pass":
        return 0

    # SKIPs happened and the operator wants to be told. Annotate +
    # decide exit code based on the mode.
    msg = (
        f"{counts['SKIP']} image(s) SKIPped — no real validation "
        "happened. RunPod had no capacity on every candidate instance "
        "type, or every candidate landed on a stuck host. "
        "Set ON_SKIP=pass to silence this, ON_SKIP=warn to keep the "
        "job green with a warning, or ON_SKIP=fail (default) to make "
        "it fatal."
    )
    print()
    if config.ON_SKIP == "warn":
        print(f"::warning::{msg}")
        return 0
    # 'fail' — also the safe default for any unknown value (coerced
    # in config._coerce_on_skip).
    print(f"::error::{msg}")
    return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    manifest_path, group_filter = _parse_args()

    rc = _check_prereqs(manifest_path)
    if rc is not None:
        return rc

    _init_gpu_catalog()
    _init_registry_auth()

    manifest = parse_manifest(manifest_path)
    try:
        _apply_manifest_overrides(manifest)
    except ValueError as exc:
        log(f"error: {exc}")
        return 1

    resolved = _resolve_all_instances(manifest)
    _warn_unknown_instances(resolved)
    _warn_unviable_cuda_axis(manifest, resolved)
    _log_budget_picks(manifest, resolved)

    results: list[Result] = []
    jobs = _build_jobs(manifest, resolved, group_filter, results)
    _run_jobs(jobs, results)

    return _print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
