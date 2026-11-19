#!/usr/bin/env python3
"""Replace torch's pip CUDA libraries with symlinks to the image's copies.

A library switches only when the wheel targets the image's CUDA major, the
soname matches and the system copy is the same minor release as pip's with an
equal or newer patch, so torch keeps the version it was tested with. The
toolkit libraries switch all together or not at all; cuDNN and NCCL decide on
their own.
Everything else stays as pip installed it.

Usage: dedupe-cuda-libs.py [--dry-run]
"""

import importlib.metadata as md
import json
import os
import re
import sys

SYSTEM_DIRS = (
    "/usr/local/cuda/lib64",
    "/usr/local/cuda/extras/CUPTI/lib64",
    "/usr/lib/x86_64-linux-gnu",
)
# Must all be replaceable for the toolkit group to switch.
TOOLKIT = {"cublas", "cuda-runtime", "cuda-nvrtc", "cufft", "curand",
           "cusolver", "cusparse", "nvjitlink"}
# Standalone: switch on their own when compatible, never block the toolkit.
STANDALONE = {"cudnn", "nccl", "cufile"}


def vt(text):
    return tuple(int(x) for x in re.findall(r"\d+", text))


def mismatch(sys_ver, pip_ver):
    """Why the system copy can not stand in for pip's, or None if it can.

    A newer minor release changes kernels and speed (cuDNN 9.8 for torch's
    9.5 ran fp32 conv 8% slower), so only a newer patch may replace pip's.
    """
    n = min(len(sys_ver), len(pip_ver), 3)
    if sys_ver[:n] < pip_ver[:n]:
        return "older than"
    if sys_ver[:2] != pip_ver[:2]:
        return "a newer minor release than"
    return None


def system_lib(d, name):
    """(soname, soname link, version) for a real library file, else None."""
    m = re.match(r"^(lib[^/]+?\.so\.(\d+))\.(\d+(?:\.\d+)*)$", name)
    path = os.path.join(d, name)
    if not m or os.path.islink(path) or not os.path.isfile(path):
        return None
    # Link to the soname symlink, which apt repoints when it upgrades the file.
    link = os.path.join(d, m.group(1))
    if os.path.realpath(link) != path:
        return None
    return m.group(1), link, vt(m.group(2) + "." + m.group(3))


def system_libs():
    """soname -> (soname link, version) for the system CUDA libraries."""
    found = {}
    for d in {os.path.realpath(x) for x in SYSTEM_DIRS if os.path.isdir(x)}:
        for name in os.listdir(d):
            hit = system_lib(d, name)
            if hit and (hit[0] not in found or hit[2] > found[hit[0]][1]):
                found[hit[0]] = hit[1:]
    return found


def plan_package(dist, system):
    """Return (list of (pip file, system file, size), reason it is kept)."""
    libs = []
    for f in dist.files or ():
        path = str(f.locate())
        if ".so" in os.path.basename(path) and os.path.isfile(path) \
                and not os.path.islink(path):
            libs.append((path, os.path.getsize(path)))
    if not libs:
        return [], "no shared libraries"
    pip_ver = vt(dist.version)
    plan = []
    for path, size in libs:
        hit = system.get(os.path.basename(path))
        if hit is None:
            # No system copy (e.g. libnvrtc.alt): keep pip's file.
            continue
        why = mismatch(hit[1], pip_ver)
        if why:
            return [], (f"system {os.path.basename(hit[0])} "
                        f"{'.'.join(map(str, hit[1]))} is {why} pip {dist.version}")
        plan.append((path, hit[0], size))
    return plan, None if plan else "no system copy"


def image_cuda_major():
    ver = os.environ.get("CUDA_VERSION", "")
    if not ver and os.path.isfile("/usr/local/cuda/version.json"):
        with open("/usr/local/cuda/version.json") as f:
            ver = json.load(f).get("cuda", {}).get("version", "")
    return vt(ver)[0] if vt(ver) else None


def nvidia_packages():
    """Installed nvidia-* distributions, keyed without the -cu12/-cu13 suffix."""
    packages = {}
    for dist in md.distributions():
        name = (dist.metadata["Name"] or "").lower().replace("_", "-")
        if name.startswith("nvidia-"):
            packages[re.sub(r"-cu1\d$", "", name[len("nvidia-"):])] = dist
    return packages


def decide(packages, system):
    """(dist, plan, reason it is kept or None) for every package considered."""
    plans = {k: plan_package(d, system) for k, d in packages.items()
             if k in TOOLKIT | STANDALONE}
    toolkit = [k for k in plans if k in TOOLKIT]
    toolkit_ok = toolkit and all(plans[k][0] and not plans[k][1] for k in toolkit)
    for key, (plan, why) in sorted(plans.items()):
        if key in TOOLKIT and not toolkit_ok and not why:
            why = "another CUDA toolkit library can not switch"
        yield packages[key], plan, why


def main():
    dry = "--dry-run" in sys.argv
    packages = nvidia_packages()

    # cuDNN/NCCL share sonames across CUDA majors, so require matching majors.
    image_major = image_cuda_major()
    runtime = packages.get("cuda-runtime")
    wheel_major = vt(runtime.version)[0] if runtime else None
    saved = 0
    if image_major is None or wheel_major != image_major:
        print(f"keep  everything: wheel CUDA {wheel_major}, image CUDA {image_major}")
        packages = {}

    for dist, plan, why in decide(packages, system_libs()):
        if why:
            print(f"keep  {dist.metadata['Name']} {dist.version}: {why}")
            continue
        for path, target, _ in plan:
            if not dry:
                os.remove(path)
                os.symlink(target, path)
        size = sum(s for _, _, s in plan)
        saved += size
        print(f"link  {dist.metadata['Name']} {dist.version}: "
              f"{len(plan)} libs, {size / 1e6:.0f} MB -> system")
    print(f"total {saved / 1e9:.2f} GB {'would be ' if dry else ''}"
          "replaced by symlinks to the system CUDA libraries")


if __name__ == "__main__":
    main()
