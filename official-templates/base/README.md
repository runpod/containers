### Runpod Base

**A lean, flexible starting point for machine learning workflows.**

The Runpod Base images provide a clean, developer friendly environment for everything from quick experiments to production, supporting both GPU and CPU-only workloads. Use them standalone for a preconfigured workspace, or as the foundation for your own images.

### What's included
- **Multiple Python versions**: 3.9–3.13 preinstalled; 3.10 is the default.
- **ML ready**: Essential libraries for scientific computing, computer vision, and machine learning, plus SLURM support.
- **Developer friendly**: SSH server preconfigured for seamless remote development and debugging.
- **Smart workspace**: Optimized directory structure and package caches for faster dependency installation.
- **Performance tuned**: Environment variables and cache strategies optimized for faster builds and execution.
- **Jupyter ready (optional)**: Notebook and JupyterLab with widgets/extensions; enable by setting `JUPYTER_PASSWORD` (omit to disable).

### Available configurations
- **Ubuntu**: 22.04 (Jammy) and 24.04 (Noble)
- **CUDA**: 12.8.0, 12.8.1, 12.9.0, and 13.0.0

Need something more specialized? Explore the templates in `official-templates` for ROCm, PyTorch, and more.

<div class="base-images">

## Generated Images

### Base Images (CPU-Only, No GPU Drivers):
- Ubuntu 22.04: `runpod/base:1.0.2-ubuntu2204`
- Ubuntu 24.04: `runpod/base:1.0.2-ubuntu2404`

### CUDA Images (GPU Required) by Version:
- 12.8.0:
    - Ubuntu 22.04: `runpod/base:1.0.2-cuda1280-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:1.0.2-cuda1280-ubuntu2404`
- 12.8.1:
    - Ubuntu 22.04: `runpod/base:1.0.2-cuda1281-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:1.0.2-cuda1281-ubuntu2404`
- 12.9.0:
    - Ubuntu 22.04: `runpod/base:1.0.2-cuda1290-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:1.0.2-cuda1290-ubuntu2404`
- 13.0.0:
    - Ubuntu 22.04: `runpod/base:1.0.2-cuda1300-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:1.0.2-cuda1300-ubuntu2404`
</div>
