# runpod/pytorch

**PyTorch-optimized images for deep learning workflows.**

Built on our base images, these PyTorch containers come pre-configured with specific PyTorch versions and CUDA support, eliminating the guesswork of compatibility and setup time. Whether you're training neural networks, running inference, or developing ML models, these images provide the exact PyTorch environment you need.

**What makes these optimized:**
- **Precision-matched versions** — Each image contains a specific PyTorch version paired with the optimal CUDA toolkit
- **Zero configuration** — PyTorch is installed and ready to import, no pip installs or environment setup required
- **GPU-accelerated** — All images include CUDA support for immediate GPU acceleration
- **Production-ready** — Built on our stable base images with all the development tools and workspace setup you need

**Choose your combination:**
- **PyTorch versions:** 2.4.0 through 2.7.1
- **CUDA versions:** 12.4.1 through 12.9.0
- **Ubuntu versions:** 22.04 and 24.04

Perfect for research, development, and production PyTorch workloads without the setup overhead.

Please also see [../base/README.md](../base/README.md)

<div class="base-images">

## Available PyTorch Images

### CUDA 12.4.1:
- Torch 2.4.0:
  - Ubuntu 22.04: `runpod/pytorch:0.7.0-cu1241-torch240-ubuntu2204`
- Torch 2.4.1:
  - Ubuntu 22.04: `runpod/pytorch:0.7.0-cu1241-torch241-ubuntu2204`
- Torch 2.5.0:
  - Ubuntu 22.04: `runpod/pytorch:0.7.0-cu1241-torch250-ubuntu2204`
- Torch 2.5.1:
  - Ubuntu 22.04: `runpod/pytorch:0.7.0-cu1241-torch251-ubuntu2204`
- Torch 2.6.0:
  - Ubuntu 20.04: `runpod/pytorch:0.7.0-cu1241-torch260-ubuntu2004`
  - Ubuntu 22.04: `runpod/pytorch:0.7.0-cu1241-torch260-ubuntu2204`

### CUDA 12.8.1:
- Torch 2.6.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1281-torch260-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1281-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1281-torch271-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1281-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1281-torch280-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1281-torch280-ubuntu2404`

### CUDA 12.9.0:
- Torch 2.6.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1290-torch260-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1290-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1290-torch271-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1290-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1290-torch280-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1290-torch280-ubuntu2404`

### CUDA 13.0.0:
- Torch 2.6.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1290-torch260-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1290-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1290-torch271-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1290-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 22.04: `runpod/pytorch:1.0.0-cu1300-torch280-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.0.0-cu1300-torch280-ubuntu2404`

*Search for more on the [Docker Hub](https://hub.docker.com/r/runpod/pytorch/tags)*

</div>