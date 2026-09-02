#!/usr/bin/env python3
"""Generate a test manifest YAML for tests/test_images.py.

Reads a JSON array of image refs (as produced by .github/actions/image-name)
and groups them into one or more manifest groups. The `profile` argument
picks the **grouping strategy**, not an image kind:

  base  Split refs into two groups by tag content:
          base_cpu : refs whose tag has NO GPU markers (run on CPU pod)
          base_gpu : refs with cuda / pytorch / py / rocm markers
        Used by runpod/base which builds both CPU- and GPU-targeted tags
        in a single matrix.
  gpu   All refs into a single `base_gpu` group with the budget / vRAM /
        manufacturer filter applied. Used by every pure-GPU workflow
        (autoresearch, pytorch, nvidia-pytorch, rocm) since they don't
        need the CPU split.

Note: the manifest group name is informational only. tests/runpod_smoke
selects the per-image functional check (nvidia-smi vs torch.cuda vs
rocm-smi vs skip) from the **image ref itself**, not from the group name.

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
            "min_cuda_version",
            "test_jupyter",
            "check_all_gpu",
            "test_comfyui",
            "test_comfyui_functional",
        ):
            if key in body:
                val = body[key]
                if isinstance(val, bool):
                    val = "true" if val else "false"
                lines.append(f"    {key}: {val}")
        if body.get("test_ports"):
            lines.append("    test_ports:")
            for port in body["test_ports"]:
                lines.append(f"    - {port}")
        # cuda_versions is either the literal `all` or a list of X.Y
        # versions; the scalar form goes through the key loop above.
        if isinstance(body.get("cuda_versions"), list):
            lines.append("    cuda_versions:")
            for version in body["cuda_versions"]:
                lines.append(f"    - {version}")
        elif body.get("cuda_versions"):
            lines.append(f"    cuda_versions: {body['cuda_versions']}")
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
    test_ports: list[int] | None = None,
    test_comfyui: bool = False,
    test_comfyui_functional: bool = False,
    check_all_gpu: bool = False,
    instances: list[str] | None = None,
    exclude_instances: list[str] | None = None,
    min_cuda_version: str | None = None,
    cuda_versions: list[str] | None = None,
    explicit_budget: bool = False,
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

    `cuda_versions` turns on the GPU x CUDA axis: `['all']` tests every
    version each GPU reports capacity for, an explicit list tests just
    those. Each version becomes its own job and is pinned with
    `gpu.allowedCudaVersions`, so it supersedes `min_cuda_version` — the
    API rejects both fields on one request.

    `min_cuda_version` is the floor CUDA driver version (X.Y) the pod's
    host driver must support. test_images.py only consults this for
    images whose tag has no embedded CUDA marker (NGC nvidia-pytorch:25.11
    and similar opaque tags); for runpod/* tags it's derived from the tag
    itself. Use this for NGC PyTorch which ships torch built against
    CUDA 13.0 and refuses to run on hosts with a 12.x driver.
    """
    exclude_instances = list(exclude_instances or [])
    instances = list(instances or [])
    test_ports = list(test_ports or [])
    cuda_versions = list(cuda_versions or [])
    wants_all_cuda = any(v.strip().lower() == "all" for v in cuda_versions)

    if instances and check_all_gpu:
        raise ValueError(
            "instances and check_all_gpu are mutually exclusive: an explicit "
            "list wins over catalog selection, so passing both silently "
            "ignores one of them"
        )

    def _decorate(body: dict, *, gpu_group: bool) -> dict:
        if gpu_group and instances:
            # An explicit list wins over catalog selection in
            # instances.resolve_instances, so the budget / vRAM / vendor
            # filters would be dead weight in the manifest.
            body["instances"] = list(instances)
        elif gpu_group:
            if check_all_gpu:
                body["check_all_gpu"] = True
                # A matrix run means EVERY GPU by default — no price filter.
                # A budget is honoured only when the caller passed one
                # explicitly, as a deliberate way to trim an expensive sweep.
                if explicit_budget:
                    body["max_price_per_hour"] = budget
            else:
                body["max_price_per_hour"] = budget
            body["min_vram_gb"] = min_vram_gb
            body["manufacturer"] = manufacturer
        if test_jupyter:
            body["test_jupyter"] = True
        if test_ports:
            body["test_ports"] = list(test_ports)
        if test_comfyui:
            body["test_comfyui"] = True
        if test_comfyui_functional:
            body["test_comfyui_functional"] = True
        if exclude_instances:
            body["exclude_instances"] = list(exclude_instances)
        if gpu_group and wants_all_cuda:
            body["cuda_versions"] = "all"
        elif gpu_group and cuda_versions:
            body["cuda_versions"] = list(cuda_versions)
        # The floor is meaningless once exact versions are pinned, and
        # sending both makes the API reject the create outright.
        if min_cuda_version and not (gpu_group and (wants_all_cuda or cuda_versions)):
            body["min_cuda_version"] = min_cuda_version
        return body

    if profile == "base":
        # Split refs into CPU- vs GPU-targeted images by tag content.
        # CPU images: the harness picks a CPU flavor from
        #   GET /v2/catalog/cpus, so CPU groups carry no `instances:` or
        #   `max_price_per_hour:` field.
        # GPU images: tested with the normal --gpu-id flow and budget filter.
        cpu = [r for r in refs if not is_gpu_ref(r)]
        gpu = [r for r in refs if is_gpu_ref(r)]
        groups: dict = {}
        if cpu:
            groups["base_cpu"] = _decorate({"images": cpu}, gpu_group=False)
        if gpu:
            groups["base_gpu"] = _decorate({"images": gpu}, gpu_group=True)
        return groups

    if profile == "gpu":
        # Pure GPU workflow: every ref goes into one group with the budget
        # filter. The functional check (nvidia-smi vs torch.cuda vs rocm-smi)
        # is picked from the IMAGE REF by runpod_smoke.checks, so the group
        # name 'base_gpu' is purely conventional here.
        return {
            "base_gpu": _decorate({"images": refs}, gpu_group=True)
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
        choices=["base", "gpu"],
    )
    ap.add_argument(
        "--refs",
        required=True,
        help="JSON array of image refs (output of .github/actions/image-name)",
    )
    ap.add_argument(
        "--budget",
        type=float,
        default=None,
        help=(
            "Max USD/hr for GPU instance selection (default: 1.0). Ignored "
            "under --check-all-gpu unless passed explicitly, since a matrix "
            "run is meant to cover every GPU."
        ),
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
        "--test-port",
        action="append",
        default=[],
        type=int,
        metavar="PORT",
        help="HTTP port to expose and probe. Repeat for multiple ports.",
    )
    ap.add_argument("--test-comfyui", action="store_true")
    ap.add_argument("--test-comfyui-functional", action="store_true")
    ap.add_argument("--check-all-gpu", action="store_true")
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
    ap.add_argument(
        "--min-cuda-version",
        default="",
        metavar="X.Y",
        help=(
            "Floor CUDA driver version that the pod's host must support "
            "(e.g. '13.0'). Emitted as `min_cuda_version` on every produced "
            "group. test_images.py uses it for images whose tag has no "
            "embedded CUDA marker — NGC nvidia-pytorch:25.11 and similar. "
            "Empty (default) = no floor."
        ),
    )
    ap.add_argument(
        "--cuda-version",
        action="append",
        default=[],
        dest="cuda_versions",
        metavar="X.Y|all",
        help=(
            "Turn on the GPU x CUDA axis: test each candidate GPU once per "
            "CUDA version instead of once overall. Repeat for several "
            "versions, or pass 'all' to use every version each GPU reports "
            "capacity for. Versions are pinned exactly via "
            "gpu.allowedCudaVersions, so this supersedes --min-cuda-version."
        ),
    )
    ap.add_argument(
        "--instance",
        action="append",
        default=[],
        dest="instances",
        metavar="DISPLAY_NAME",
        help=(
            "Test exactly this GPU display name (repeat for several). "
            "Emitted as `instances:`, which wins over catalog selection — so "
            "it cannot be combined with --check-all-gpu, and the budget / "
            "vRAM / vendor filters no longer apply."
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

    if args.instances and args.check_all_gpu:
        print(
            "--instance and --check-all-gpu are mutually exclusive: an "
            "explicit instance list wins over catalog selection",
            file=sys.stderr,
        )
        return 1

    groups = build_groups(
        args.profile,
        refs,
        budget=1.0 if args.budget is None else args.budget,
        explicit_budget=args.budget is not None,
        min_vram_gb=args.min_vram_gb,
        manufacturer=args.manufacturer,
        test_jupyter=args.test_jupyter,
        test_ports=args.test_port,
        test_comfyui=args.test_comfyui,
        test_comfyui_functional=args.test_comfyui_functional,
        check_all_gpu=args.check_all_gpu,
        instances=args.instances,
        exclude_instances=args.exclude_instance,
        min_cuda_version=(args.min_cuda_version or None),
        cuda_versions=args.cuda_versions,
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
