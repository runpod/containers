### Runpod Base

**A lean, flexible starting point for machine learning workflows.**

The Runpod Base images provide a clean, developer friendly environment for everything from quick experiments to production, supporting both GPU and CPU-only workloads. Use them standalone for a preconfigured workspace, or as the foundation for your own images.

### What's included
- **Multiple Python versions**: 3.10–3.13 preinstalled; 3.12 is the default.
- **ML ready**: Essential libraries for scientific computing, computer vision, and machine learning, plus SLURM support.
- **Developer friendly**: SSH server preconfigured for seamless remote development and debugging.
- **Smart workspace**: Optimized directory structure and package caches for faster dependency installation.
- **Performance tuned**: Environment variables and cache strategies optimized for faster builds and execution.
- **Jupyter ready (optional)**: Notebook and JupyterLab with widgets/extensions. Set `JUPYTER_PASSWORD` and it becomes the login token; omit it and JupyterLab does not start. `JUPYTER_DISABLE_AUTH=true` runs it with no password and takes precedence over `JUPYTER_PASSWORD` — the `:8888` proxy URL is public, so anyone with it gets a root shell.

> **Python 3.9 removed.** It reached end-of-life (Oct 2025) and no longer gets a security-patched pip, so runpod/base now ships Python 3.11–3.13. To migrate: recreate any 3.9 virtualenv with a supported interpreter (`python3.12 -m venv .venv`) and reinstall your dependencies. The default `python`, `pip` and `python3` point to 3.12, so plain `python ...` keeps working.

> **Ubuntu 22.04 and Python 3.10 removed.** `-ubuntu2204` tags are no longer built; the last published ones stay pullable but get no updates. Python 3.10 went with it — it was only shipped as 22.04's system interpreter. To migrate, swap `ubuntu2204` for `ubuntu2404` in your tag (same CUDA version, same default Python 3.12) and recreate any 3.10 virtualenv as above. The CPU-only image is also available on Ubuntu 26.04 (`-ubuntu2604`); CUDA images stay on 24.04 until NVIDIA ships 26.04 builds of these CUDA versions.

> **`python3` and apt packages.** `python`, `python3` and `pip` all point to 3.12. Packages installed with `apt install python3-*` are built for the Ubuntu release's own interpreter and are only importable from `/usr/bin/python3` — 3.14 on 26.04 (on 24.04 that is 3.12 itself). Python 3.11–3.13 don't see them, so for those use `pip install`. The same goes for scripts starting with `#!/usr/bin/env python3` that need an apt-installed module: run them with `/usr/bin/python3`. On 26.04 the image has no `add-apt-repository`; add a PPA by hand, or `apt-get install software-properties-common`.

> **CUDA images: smaller toolkit install.** The CUDA images used to be up to 5.7 GB larger than needed. The toolkit is the same as NVIDIA's `cudnn-devel` image: `nvcc`, headers, every shared library and the cuDNN/NCCL dev files, at the versions the tag names. Two things are left out:
>
> - **Static libraries** (`lib*_static.a`, 1.3–2.4 GB; `libcudart_static.a` is kept). To get one back, reinstall its package at the installed version, e.g. `apt-get install --reinstall "libcufft-dev-12-8=$(dpkg-query -W -f='${Version}' libcufft-dev-12-8)"`. Without the `=version`, apt moves the library to the newest patch release instead.
> - **Nsight Compute** (`ncu`). To install it: `apt-get install cuda-nsight-compute-12-8` (use your CUDA version).
>
> CUDA packages also no longer move to a newer patch release than the tag names (12.9.0 used to ship parts of 12.9.1).

### Available configurations
- **Ubuntu**: 24.04 (Noble); CPU-only also on 26.04 (Resolute)
- **CUDA**: 12.8.1, 12.9.0, 13.0.0, and 13.2.0 (Ubuntu 24.04)

Need something more specialized? Explore the templates in `official-templates` for ROCm, PyTorch, and more.

<div class="base-images">

## Generated Images

### Base Images (CPU-Only, No GPU Drivers):
- Ubuntu 24.04: `runpod/base:<template-tag>-ubuntu2404`
- Ubuntu 26.04: `runpod/base:<template-tag>-ubuntu2604`

### CUDA Images (GPU Required) by Version:
- 12.8.1:
    - Ubuntu 24.04: `runpod/base:<template-tag>-cuda1281-ubuntu2404`
- 12.9.0:
    - Ubuntu 24.04: `runpod/base:<template-tag>-cuda1290-ubuntu2404`
- 13.0.0:
    - Ubuntu 24.04: `runpod/base:<template-tag>-cuda1300-ubuntu2404`
- 13.2.0:
    - Ubuntu 24.04: `runpod/base:<template-tag>-cuda1320-ubuntu2404`
</div>
