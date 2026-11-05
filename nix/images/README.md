# Nix-built images

Counterparts of `runpod/base`, `runpod/pytorch` and `runpod/rocm`, built
from nixpkgs alone: no Ubuntu base, no apt, no pip. Every input is pinned by
`flake.lock`. Build-only; nothing is published.

```sh
nix run .#image-size                 # build all, compare with Docker Hub
nix run .#image-smoke -- nix-base-cpu
nix build .#nix-pytorch-cuda && ./result | docker load
```

CUDA comes from the NixOS CUDA team's cache. Add it for the command if you're
a trusted user (`image-size` does this), or in `nix.conf`:

```sh
--option extra-substituters https://cache.nixos-cuda.org \
--option extra-trusted-public-keys cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M=
```

## Size

Compressed (≈ what a pod pulls), against the latest published release:

| Nix image | Nix | published image | published | change |
| --- | ---: | --- | ---: | ---: |
| `nix-base-cpu` | 689 MB | `base:1.6.0-ubuntu2404` | 701 MB | -1% |
| `nix-base-cpu-runtime` | 345 MB | `base:1.6.0-ubuntu2404` | 701 MB | -50% |
| `nix-base-cuda` | 2374 MB | `base:1.6.0-cuda1320-ubuntu2404` | 6714 MB | -64% |
| `nix-pytorch-cuda` | 5155 MB | `pytorch:1.6.0-cu1320-torch2130-ubuntu2404` | 9525 MB | -45% |
| `nix-pytorch-rocm` | 7885 MB | `rocm:1.6.0-rocm644-ubuntu2404-py312-pytorch271` | 27607 MB | -71% |

- **GPU images:** the savings come from shipping only the CUDA/ROCm libraries
  the stack uses, instead of a vendor `-devel` base image.
- **CPU:** the build toolchain (gcc, gfortran, cmake) is most of the image.
  With it, Nix matches apt; `nix-base-cpu-runtime` drops it.

## Versions

One version of each, nixpkgs' current: Python 3.14, torch 2.14.1, CUDA 13.4
(cuDNN 9.27), ROCm 7.2. Not the published images' version matrix.

## How it fits the pod contract

- `container-template/start.sh` runs unchanged. A `service` shim starts nginx
  and sshd, since there's no init system.
- `/etc/passwd`, `sshd_config` and `sudoers` are written by hand, since
  there's no apt to do it.
- **Prebuilt binaries** (pip wheels, uv-managed Pythons, VS Code server)
  expect a distro: `/lib64/ld-linux-x86-64.so.2` is
  [nix-ld](https://github.com/nix-community/nix-ld), and the manylinux
  libraries (libstdc++, zlib, libGL, ...) are on `LD_LIBRARY_PATH`. sshd sets
  these too, because SSH sessions don't inherit the image's `ENV`.
- **NVIDIA driver:** nvidia-container-toolkit mounts the driver into
  `/usr/lib/x86_64-linux-gnu`, and `/run/opengl-driver/lib` (where nixpkgs'
  CUDA looks) links to it.

## Tested

- **`image-smoke`** (CI, CPU image): SSH, sftp, JupyterLab static assets
  (#168), nginx, TLS, a pip wheel, a uv-managed Python, and sshd/Jupyter
  staying off without `PUBLIC_KEY`/`JUPYTER_PASSWORD`.
- **`nix-pytorch-cuda`**, by hand on an RTX 3070 with the host driver mounted
  where the toolkit puts it: CUDA, cuDNN and `torch.compile` (GPU and CPU)
  work.
- **`nix-pytorch-rocm`**: imports, reports HIP 7.2, and targets gfx942/gfx950
  (MI300X/MI355X). Not run on an AMD GPU.

## Not yet

- **Pod test:** nothing has run on a Runpod pod yet. Needs a registry push.
- **pip upgrades:** `pip install` as root writes into the Nix Python
  environment, so upgrading a package the image ships replaces Nix's copy
  in place. Virtualenvs and `uv` are unaffected.
- **DSA host key:** OpenSSH 10 can't generate one, so the image ships an
  empty placeholder for start.sh to skip. Dropping DSA from start.sh would
  fix that for every image.
