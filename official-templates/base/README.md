### Runpod Base

**A lean, flexible starting point for machine learning workflows.**

Runpod Base images provide a clean, developer-friendly environment that scales from quick experiments to production. Use them as-is for instant productivity or as the foundation for your own images.

### What's included
- **Jupyter-ready (optional)**: Notebook and JupyterLab with widgets/extensions; enable by setting `JUPYTER_PASSWORD` (omit to disable).
- **Multiple Python versions**: 3.9–3.13 preinstalled; 3.10 is the default.
- **Smart workspace layout**: Preconfigured directories and cache paths for faster package installs.
- **Developer tooling**: SSH for remote development and NGINX for serving web apps.
- **ML-ready libraries**: Core dependencies for scientific computing, imaging, and ML workflows.
- **Optimized performance**: Sensible environment variables and cache locations for efficient builds and runtime.

### Available configurations
- **Ubuntu**: 22.04 and 24.04
- **CUDA**: 12.8.0, 12.8.1, 12.9.0, and 13.0.0

Perfect for rapid prototyping, day‑to‑day development, and as a base layer for specialized images.

Need something more specialized? Explore the templates in `official-templates` for ROCm, PyTorch, and other ML frameworks.

<div class="base-images">

## Generated Images

### Operating Systems:
- Ubuntu 22.04: `runpod/base:0.7.0-ubuntu2204`
- Ubuntu 24.04: `runpod/base:0.7.0-ubuntu2404`

### CUDA Versions:
- 12.8.0:
    - Ubuntu 22.04: `runpod/base:0.7.0-cuda1280-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:0.7.0-cuda1280-ubuntu2404`
- 12.8.1:
    - Ubuntu 22.04: `runpod/base:0.7.0-cuda1281-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:0.7.0-cuda1281-ubuntu2404`
- 12.9.0:
    - Ubuntu 22.04: `runpod/base:0.7.0-cuda1290-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:0.7.0-cuda1290-ubuntu2404`
- 13.0.0:
    - Ubuntu 22.04: `runpod/base:0.7.0-cuda1300-ubuntu2204`
    - Ubuntu 24.04: `runpod/base:0.7.0-cuda1300-ubuntu2404`

</div>
