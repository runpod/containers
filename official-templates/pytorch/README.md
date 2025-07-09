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
- **Ubuntu versions:** 20.04, 22.04, and 24.04

Perfect for research, development, and production PyTorch workloads without the setup overhead.

Please also see [../base/README.md](../base/README.md)

<div class="base-images">

## Generated PyTorch Images

### CUDA 12.4.1:
- Torch 2.4.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch240-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1241-torch240`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch240-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1241-torch240`
- Torch 2.4.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch241-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1241-torch241`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch241-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1241-torch241`
- Torch 2.5.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch250-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1241-torch250`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch250-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1241-torch250`
- Torch 2.5.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch251-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1241-torch251`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch251-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1241-torch251`
- Torch 2.6.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch260-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1241-torch260`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1241-torch260-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1241-torch260`

### CUDA 12.5.1:
- Torch 2.5.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1251-torch251-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1251-torch251`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1251-torch251-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1251-torch251`
- Torch 2.6.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1251-torch260-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1251-torch260`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1251-torch260-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1251-torch260`

### CUDA 12.6.3:
- Torch 2.6.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch260-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1263-torch260`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch260-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1263-torch260`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch260-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1263-torch260`
- Torch 2.7.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch271-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1263-torch271`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch271-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1263-torch271`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1263-torch271-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1263-torch271`

### CUDA 12.8.1:
- Torch 2.6.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch260-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1281-torch260`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch260-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1281-torch260`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch260-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1281-torch260`
- Torch 2.7.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch271-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1281-torch271`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch271-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1281-torch271`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1281-torch271-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1281-torch271`

### CUDA 12.9.0:
- Torch 2.6.0:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch260-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1290-torch260`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch260-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1290-torch260`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch260-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1290-torch260`
- Torch 2.7.1:
  - Ubuntu 20.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch271-ubuntu2004`
    - `runpod/pytorch:0.7.0-dev-ubuntu2004-cu1290-torch271`
  - Ubuntu 22.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch271-ubuntu2204`
    - `runpod/pytorch:0.7.0-dev-ubuntu2204-cu1290-torch271`
  - Ubuntu 24.04:
    - `runpod/pytorch:0.7.0-dev-cu1290-torch271-ubuntu2404`
    - `runpod/pytorch:0.7.0-dev-ubuntu2404-cu1290-torch271`

</div>