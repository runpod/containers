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
        for key in ("max_price_per_hour", "min_vram_gb", "manufacturer"):
            if key in body:
                lines.append(f"    {key}: {body[key]}")
    return "\n".join(lines) + "\n"


def build_groups(
    profile: str,
    refs: list[str],
    *,
    budget: float,
    min_vram_gb: int,
    manufacturer: str,
) -> dict:
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
            groups["base_cpu"] = {"images": cpu}
        if gpu:
            groups["base_gpu"] = {
                "images": gpu,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            }
        return groups

    if profile == "autoresearch":
        # autoresearch images always extend a GPU base; reuse base_gpu so
        # test_images.py runs the nvidia-smi check on them.
        return {
            "base_gpu": {
                "images": refs,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            }
        }

    if profile == "pytorch":
        # 'pytorch' triggers the torch.cuda functional check in test_images.py.
        return {
            "pytorch": {
                "images": refs,
                "max_price_per_hour": budget,
                "min_vram_gb": min_vram_gb,
                "manufacturer": manufacturer,
            }
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
