#!/usr/bin/env python3
"""Generate a test manifest YAML for tests/test_images.py.

Reads a JSON array of image refs (as produced by .github/actions/image-name)
and groups them according to the build profile:

  base profile          base_cpu : refs whose tag has NO GPU markers
                        base_gpu : refs whose tag has any of the GPU markers
                                   (cuda / pytorch / py / rocm)
  autoresearch profile  base_gpu : all refs (uses nvidia-smi functional check
                                   — autoresearch always runs on GPU base)
  pytorch profile       pytorch  : all refs (uses torch.cuda functional check)

The group names matter: tests/test_images.py special-cases them in
cuda_check_command() to pick the right per-group validation routine.

Usage:
    generate_test_manifest.py --profile base \\
        --refs '["docker.io/runpod/base:1.0.6-...-ubuntu2204", ...]' \\
        --budget 1.0 \\
        --output manifest.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# A tag is treated as GPU iff it contains any of these (case-insensitive)
# substrings. Matches our actual tag conventions:
#   runpod/base:...-cuda1281-ubuntu2204                  -> cuda
#   runpod/base:...-rocm644-ubuntu2204-py310-pytorch251  -> rocm, py, pytorch
#   runpod/pytorch:...-cuda1281-py3.10-pytorch251-...    -> cuda, py, pytorch
# CPU base images carry only ubuntu+suffix, none of these substrings.
GPU_TAG_PATTERN = re.compile(r"(cuda|pytorch|py|rocm)", re.IGNORECASE)


def is_gpu_ref(ref: str) -> bool:
    """A ref is GPU iff its tag (post-colon) contains a GPU marker."""
    _, _, tag = ref.rpartition(":")
    return bool(GPU_TAG_PATTERN.search(tag))


def render_yaml(groups: dict) -> str:
    """Hand-rolled YAML emitter so the runner doesn't need PyYAML.

    Output shape matches tests/test_images.py's minimal YAML parser, which
    is strict about indentation: 4 spaces for list keys / scalar keys
    inside a group, then a bare `- value` for list items also at 4 spaces.
    Don't change this without also relaxing parse_manifest() in test_images.py.

    Strings are unquoted — safe for our values which are image refs,
    instance names, floats, and single-word manufacturer names.
    Booleans are emitted as the lowercase `true`/`false` literals
    test_images.py's parser recognises.
    """
    lines: list[str] = []
    for grp_name, body in groups.items():
        lines.append(f"{grp_name}:")
        lines.append("    images:")
        for img in body["images"]:
            lines.append(f"    - {img}")
        if "instances" in body:
            lines.append("    instances:")
            for inst in body["instances"]:
                lines.append(f"    - {inst}")
        for key in (
            "max_price_per_hour",
            "min_vram_gb",
            "manufacturer",
            "test_jupyter",
        ):
            if key in body:
                val = body[key]
                if isinstance(val, bool):
                    val = "true" if val else "false"
                lines.append(f"    {key}: {val}")
        # exclude_instances is a list, emitted at the bottom of the group so
        # it's visually grouped with other "filter" options. Patterns are
        # double-quoted to keep glob-leading characters ('*', '?') safe from
        # any stricter YAML parser that might consume this file later.
        if body.get("exclude_instances"):
            lines.append("    exclude_instances:")
            for pat in body["exclude_instances"]:
                lines.append(f'    - "{pat}"')
    return "\n".join(lines) + "\n"


def build_groups(
    profile: str,
    refs: list[str],
    *,
    budget: float,
    min_vram_gb: int,
    manufacturer: str,
    test_jupyter: bool = False,
    exclude_instances: list[str] | None = None,
) -> dict:
    """Build the manifest dict for `profile`.

    `test_jupyter` is opt-in (default off). When true, every group emitted
    here gets `test_jupyter: true`, which tells tests/test_images.py to
    expose 8888/http, set JUPYTER_PASSWORD, and run the in-pod + public-
    proxy Jupyter probes. Only enable this when the underlying images
    actually use container-template/start.sh (runpod/base, runpod/pytorch,
    runpod/autoresearch). NGC nvidia-pytorch images have a different
    entrypoint and would fail the probe.

    `exclude_instances` is a list of fnmatch-style patterns (e.g.
    '*Blackwell*') that test_images.py subtracts from each group's
    candidate pool. Use to block known-bad image/GPU pairings — e.g.
    PyTorch ≤ 2.6 wheels have no kernels for sm_100/sm_120, so any test
    landing on a Blackwell host fails with 'no kernel image is available
    for execution on the device'.
    """
    exclude_instances = list(exclude_instances or [])

    def _decorate(body: dict) -> dict:
        if test_jupyter:
            body["test_jupyter"] = True
        if exclude_instances:
            body["exclude_instances"] = list(exclude_instances)
        return body

    if profile == "base":
        # Split refs into CPU- vs GPU-targeted images by tag content.
        # CPU images: tested via runpodctl --compute-type CPU. RunPod selects
        #   the CPU flavor for us — runpodctl 2.3.0 doesn't expose --gpu-id
        #   for CPU, so we can't (and don't) constrain the manifest with an
        #   `instances:` or `max_price_per_hour:` field for CPU groups.
        # GPU images: tested with the normal --gpu-id flow and budget filter.
        cpu = [r for r in refs if not is_gpu_ref(r)]
        gpu = [r for r in refs if is_gpu_ref(r)]
        groups: dict = {}
        if cpu:
            groups["base_cpu"] = _decorate({"images": cpu})
        if gpu:
            groups["base_gpu"] = _decorate({
                "images": gpu,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            })
        return groups

    if profile == "autoresearch":
        # autoresearch images always extend a GPU base; reuse base_gpu so
        # test_images.py runs the nvidia-smi check on them.
        return {
            "base_gpu": _decorate({
                "images": refs,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            })
        }

    if profile == "pytorch":
        # 'pytorch' triggers the torch.cuda functional check in test_images.py.
        return {
            "pytorch": _decorate({
                "images": refs,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            })
        }

    raise ValueError(f"unknown profile: {profile!r}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--profile",
        required=True,
        choices=["base", "autoresearch", "pytorch"],
    )
    ap.add_argument(
        "--refs",
        required=True,
        help="JSON array of image refs (output of .github/actions/image-name)",
    )
    ap.add_argument(
        "--budget",
        type=float,
        default=1.0,
        help="Max USD/hr for GPU instance selection (default: 1.0)",
    )
    ap.add_argument(
        "--min-vram-gb",
        type=int,
        default=16,
        help="Min GPU vRAM filter for budget mode (default: 16)",
    )
    ap.add_argument(
        "--manufacturer",
        default="Nvidia",
        help="GPU manufacturer filter for budget mode (default: Nvidia)",
    )
    ap.add_argument(
        "--test-jupyter",
        action="store_true",
        help=(
            "Emit `test_jupyter: true` for every produced group so "
            "test_images.py exposes 8888/http, sets JUPYTER_PASSWORD, and "
            "runs the in-pod + public-proxy Jupyter probes. "
            "Off by default — enable per CI step."
        ),
    )
    ap.add_argument(
        "--exclude-instance",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "fnmatch-style pattern of GPU display names to subtract from "
            "every produced group's candidate pool. Repeat for multiple "
            "patterns. Example: --exclude-instance '*Blackwell*' "
            "--exclude-instance 'RTX A4000'. Empty = no exclusions."
        ),
    )
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    try:
        refs = json.loads(args.refs)
    except json.JSONDecodeError as exc:
        print(f"--refs is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(refs, list) or not refs:
        print("--refs must be a non-empty JSON array", file=sys.stderr)
        return 1

    groups = build_groups(
        args.profile,
        refs,
        budget=args.budget,
        min_vram_gb=args.min_vram_gb,
        manufacturer=args.manufacturer,
        test_jupyter=args.test_jupyter,
        exclude_instances=args.exclude_instance,
    )

    if not groups:
        print(
            f"No groups produced from {len(refs)} refs with profile "
            f"{args.profile!r}",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    body = render_yaml(groups)
    args.output.write_text(body)
    print(f"Wrote {args.output}:")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
