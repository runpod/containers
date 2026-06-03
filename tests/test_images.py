#!/usr/bin/env python3
"""Smoke-test RunPod container images.

Entry point. See ./README.md for the manifest schema, env vars, and how
the CUDA / Jupyter checks work. All implementation lives in the
runpod_smoke/ package next to this file.

Usage:
    ./test_images.py [path/to/images.yaml] [group_filter]

Requirements: runpodctl (logged in), python3 >= 3.9
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# When invoked via a symlink (we keep one at /tmp/runpod-scripts/testing/),
# Python puts the symlink's directory on sys.path, NOT the directory that
# actually contains the `runpod_smoke/` package. Resolve the real path so
# our package imports work regardless of how the script was launched.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from runpod_smoke import config
from runpod_smoke.instances import (
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
from runpod_smoke.runpodctl import runpodctl
from runpod_smoke.runner import test_image


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

    config.GPU_ID_MAP.update(discover_gpu_id_map())
    log(f"discovered {len(config.GPU_ID_MAP)} GPU types from runpodctl")

    config.GPU_CATALOG.extend(discover_gpu_catalog())
    if config.GPU_CATALOG:
        log(
            f"loaded GPU pricing for {len(config.GPU_CATALOG)} types "
            "(GraphQL: gpuTypes)"
        )
    else:
        log(
            "warn: no GPU pricing data — budget-based instance selection "
            "(max_price_per_hour) will be disabled. Set RUNPOD_API_KEY or "
            "ensure ~/.runpod/config.toml has 'apikey'."
        )

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

    manifest = parse_manifest(images_path)

    # Collect manifest `min_cuda_version` fallbacks. Used by create_pod
    # when an image tag doesn't encode CUDA itself (NGC `nvidia-pytorch:25.11`).
    for grp, contents in manifest.items():
        normalized = _normalize_cuda_version(contents.get("min_cuda_version"))
        if normalized:
            config.GROUP_MIN_CUDA[grp] = normalized
            log(
                f"group '{grp}': min_cuda_version={normalized} "
                "(applied when image tag has no embedded CUDA)"
            )

    # Collect manifest `test_jupyter` opt-ins. Drives both pod creation
    # (env + port) and the post-boot Jupyter probe.
    for grp, contents in manifest.items():
        flag = _normalize_bool(contents.get("test_jupyter"))
        if flag:
            config.GROUP_TEST_JUPYTER[grp] = True
            log(
                f"group '{grp}': test_jupyter=true "
                f"(JUPYTER_PASSWORD={config.JUPYTER_TEST_PASSWORD!r}, "
                "expose 8888/http)"
            )

    # Resolve the instances list for each group now (so we can warn about
    # typos / empty lists once, up front, instead of per-job). For
    # explicit-list groups this is just a copy. For budget-based groups
    # this queries the GPU catalog and picks cheapest-first. For
    # `base_cpu` it returns a single sentinel value (RunPod picks the
    # CPU flavor).
    resolved_instances: dict[str, list[str]] = {}
    for grp, contents in manifest.items():
        resolved_instances[grp] = resolve_instances(grp, contents)

    # Warn about explicit-list entries that don't match any known GPU
    # display name — these would be passed to runpodctl verbatim and
    # fail. Skip the CPU sentinel since it isn't a GPU name by design.
    unmapped = sorted({
        inst
        for grp, instances in resolved_instances.items()
        for inst in instances
        if inst != config.CPU_INSTANCE_SENTINEL and not is_known_gpu(inst)
    })
    if unmapped:
        log(
            f"warn: {len(unmapped)} instance(s) don't match any RunPod "
            "displayName — check spelling/casing:"
        )
        for inst in unmapped:
            log(f"  - {inst!r}", indent=1)

    # Log the resolved instance list per group — especially useful when
    # the user wrote `max_price_per_hour: X` and wants to see what was picked.
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
    # the summary report which GPU each test landed on (handy when an
    # image FAILed because of an unlucky host pairing, not an actual bug).
    results: dict[str, tuple[str, str, str]] = {}

    # Flatten the manifest into a list of (image, group, instances) jobs
    # that can run independently. Skip groups we can't actually exercise.
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
            f"with MAX_PARALLEL={config.MAX_PARALLEL} ===================="
        )

        if config.MAX_PARALLEL <= 1:
            # Serial mode — simpler logs, no worker tags.
            current_group = None
            for img, group, instances in jobs:
                if group != current_group:
                    print()
                    log(f"---------- group: {group} ----------")
                    current_group = group
                results[img] = test_image(img, instances, group)
        else:
            # Parallel mode — tag each pool thread so output is readable
            # when multiple pods are progressing at the same time. The
            # tag is assigned to the thread (not the job), so e.g. with
            # 5 jobs and 3 workers you still see only W1/W2/W3, each
            # handling 1-2 jobs.
            def _run_job(img: str, grp: str, insts: list[str]):
                ensure_worker_tag()
                log(f"start [group={grp}] image={img}")
                res = test_image(img, insts, grp)
                log(f"done  [group={grp}] image={img} -> {res[0]}")
                return img, res

            with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL) as pool:
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
            inst_label = (
                "CPU" if instance == config.CPU_INSTANCE_SENTINEL else instance
            )
            inst_str = f" [{inst_label}]" if inst_label else ""
            note_str = f" -- {note}" if note else ""
            print(f"  {want:6s} {img}{inst_str}{note_str}")

    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
