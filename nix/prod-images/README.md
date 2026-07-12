# Native-parity Nix container images (`prod-images`)

An attempt to rebuild the repo's containers **entirely from Nix** — replacing
every `apt`/`pip`/`uv` install with a Nix package (source-built, hash-pinned),
and CUDA with nixpkgs' own `cudaPackages` (no vendor `nvidia/cuda` base). Goal:
narHash-verified inputs (**security**), **bit-reproducibility**, and better
cross-image layer sharing. **Build-only — nothing is published.**

Kept separate from the experimental PoC in `../images/` so both approaches
coexist and can be compared. Scope here: **base + pytorch** (CPU + CUDA).

## What the current images install (review)

| image | base | Python | key installs |
| --- | --- | --- | --- |
| base | ubuntu / nvidia-cuda devel | 3.9–3.13 (deadsnakes) | apt: build-essential, ffmpeg, cmake, …; pip: jupyterlab 4.5.9, notebook 7.5.6, ipywidgets 8.1.8, hf_transfer 0.1.9, jupyter-archive 3.4.0; uv; filebrowser 2.63.5; nginx |
| pytorch | runpod/base cuda | (from base) | pip torch/torchvision/torchaudio — matrix 2.6.0–2.9.1 × cu126/128/129/130 |

Runtime contract (reproduced in `runtime.nix`): nginx proxy; `$PUBLIC_KEY`→sshd
(host-key gen); `$JUPYTER_PASSWORD`→`jupyter lab` on 8888 (`preferred_dir=/workspace`);
export env to `/etc/rp_environment`; `/pre_start.sh` + `/post_start.sh`; sleep.

## The Nix rebuild

- **`userland.nix`** — Python **3.14** env (jupyterlab/notebook/ipywidgets/hf-transfer
  + our `jupyter-archive`) plus uv, filebrowser, nginx, openssh, and the apt-parity
  dev toolchain (gcc, gnumake, cmake, gfortran, pkg-config, ffmpeg) — all Nix packages.
- **`pkgs/jupyter-archive.nix`** — the one `requirements.txt` entry missing from nixpkgs,
  packaged from the PyPI **sdist** (hash-pinned, source-built via hatchling).
- **`runtime.nix`** — Nix-adapted `/start.sh` (the upstream uses Debian `service`, absent
  here): runs `nginx`/`sshd`/`jupyter` directly, same env-var gating; stages the repo's
  nginx proxy config + banner.
- **`base.nix`** — `prod-base-cpu`, `prod-base-cuda` (+ nixpkgs `cudaPackages` CUDA 12.9 /
  cuDNN 9.22 on PATH/LD_LIBRARY_PATH; CUDA comes from NVIDIA **redistributables** =
  hash-pinned fetches, not source builds).
- **`pytorch.nix`** — `prod-pytorch-cpu` (torch 2.12.0 CPU, cache-friendly) and
  `prod-pytorch` (`cudaSupport=true`, a heavy from-source CUDA compile).

## Measured (build-only, gzip ≈ registry download)

| target | uncompressed | gzip | notes |
| --- | --- | --- | --- |
| `prod-base-cpu` | 2473 MB | **850 MB** | full dev toolchain + 1 python |
| `prod-pytorch-cpu` | 3967 MB | **1250 MB** | + torch 2.12.0 (CPU) |
| `prod-base-cuda` | 7231 MB | **3698 MB** | + nixpkgs CUDA 12.9 / cuDNN |
| `prod-pytorch` (CUDA) | _(heavy build)_ | _(pending)_ | torch source-compiled w/ CUDA |

Reference points (compressed): `runpod/base:1.0.7-ubuntu2404` (apt) = **714 MB**;
`runpod/base:1.0.7-cuda1281-ubuntu2404` = **6359 MB**.

- **CPU base**: the parity Nix base (850 MB) is a touch *larger* than apt's 714 MB —
  it bundles the full gcc/gfortran/ffmpeg dev toolchain as Nix closures, vs one Python
  (theirs has five). Net wash on size; the win is determinism + hash-pinning.
- **CUDA base**: full-Nix (3698 MB) is **~42% smaller** than the vendor-based image
  (6359 MB) — it ships only the CUDA toolkit + cuDNN redistributables, not the ~5.6 GB
  `nvidia/cuda:*-cudnn-devel` base. Plus layer sharing across the family (see
  `../images/README.md`).

## Honest caveats

- **Version drift:** native nixpkgs gives **one** torch (2.12.0) + CUDA 12.9 — newer than
  and not matching the repo's 2.6–2.9.1 × cu126–130 matrix. Inherent to source-from-nixpkgs.
- **CUDA torch build cost:** `prod-pytorch` is a long, RAM-heavy compile (unfree ⇒ absent from
  cache.nixos.org). Build locally / on a big runner and push to a cache; GH-hosted CI can't.
- **Python 3.14** vs the repo's 3.9–3.13; jupyterlab 4.5.8 vs pinned 4.5.9 (nixpkgs' version).
- **Runtime not container-tested in the sandbox:** the image builds and contains everything;
  full nginx/sshd/jupyter startup needs an actual pod/GPU host to validate.
- **Out of scope:** autoresearch, nvidia-pytorch (NGC proprietary), rocm.

## Build & verify

```sh
nix build .#packages.x86_64-linux.prod-base-cpu      # + prod-pytorch-cpu, prod-base-cuda
nix run  .#packages.x86_64-linux.prod-base-cpu | wc -c
# import check:
nix build --impure --expr '…userland.python.withPackages…' && python -c 'import jupyterlab, hf_transfer, jupyter_archive'
nix build .#packages.x86_64-linux.prod-pytorch       # heavy: local/cache only
```
