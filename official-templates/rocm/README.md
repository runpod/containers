### Runpod ROCm

**AMD GPU-accelerated images for PyTorch workloads.**

Runpod ROCm builds on `runpod/base` with the ROCm stack and PyTorch pre-configured for AMD GPU acceleration. Get immediate GPU compute without the ROCm setup complexity.

### What's included
- **ROCm 6.4.1**: Latest stable AMD GPU compute platform
- **PyTorch on ROCm**: Pre-installed and configured for immediate GPU acceleration
- **All base features**: Complete development environment from our base images (Jupyter, SSH, NGINX, ML libraries)

### Available configurations
Chose between PyTorch 2.5.1, 2.6.0, and 2.7.0, with Ubuntu 22.04 or 24.04.

Perfect for AMD GPU workloads with zero setup time.

**Note:** These images are larger than our base images, so we provide a focused selection. Need additional combinations? Let us know!

## Generated Images

<div class="base-images">

### PyTorch Versions:
- PyTorch 2.5.1: 
    - Ubuntu 22.04: `runpod/base:0.7.0-rocm641-ubuntu2204-py310-pytorch251`
- PyTorch 2.6.0: 
    - Ubuntu 22.04: `runpod/base:0.7.0-rocm641-ubuntu2204-py310-pytorch260` 
    - Ubuntu 24.04: `runpod/base:0.7.0-rocm641-ubuntu2404-py312-pytorch260`
- PyTorch 2.7.0: 
    - Ubuntu 24.04: `runpod/base:0.7.0-rocm641-ubuntu2404-py312-pytorch270`
</div>