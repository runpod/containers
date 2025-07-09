<h1>Runpod ROCm</h1>

**AMD GPU-accelerated images for PyTorch workloads.**

Runpod ROCm mirrors `runpod/base` on the `rocm/pytorch` images, providing AMD GPU acceleration for your deep learning projects. Whether you're working with Radeon Instinct, MI series, or other AMD GPUs, these images give you the ROCm stack with PyTorch pre-configured and ready to use.

**What makes these accelerated:**
- **ROCm 6.4.1** — Latest stable AMD GPU compute platform
- **PyTorch integration** — Pre-installed PyTorch with ROCm backend for immediate GPU acceleration
- **Familiar environment** — All the development tools and workspace setup from our base images
- **Multiple PyTorch versions** — Choose from 2.5.1, 2.6.0, and 2.7.0

**Choose your combination:**
- **PyTorch versions:** 2.5.1, 2.6.0, and 2.7.0
- **Ubuntu versions:** 22.04 and 24.04
- **Python versions:** 3.10 and 3.12

Perfect for AMD GPU workloads without the ROCm setup complexity.

**Important note:** These images are rather large, so we provide a slightly smaller lineup. If you need more, please let us know.

## Generated Images

<div class="base-images">

### PyTorch Versions:
- PyTorch 2.5.1:
    - Ubuntu 22.04:
        - `runpod/base:0.7.0-rocm641-ubuntu2204-py310-pytorch251`
- PyTorch 2.6.0:
    - Ubuntu 22.04:
        - `runpod/base:0.7.0-rocm641-ubuntu2204-py310-pytorch260`
    - Ubuntu 24.04:
        - `runpod/base:0.7.0-rocm641-ubuntu2404-py312-pytorch260`
- PyTorch 2.7.0:
    - Ubuntu 24.04:
        - `runpod/base:0.7.0-rocm641-ubuntu2404-py312-pytorch270`
</div>