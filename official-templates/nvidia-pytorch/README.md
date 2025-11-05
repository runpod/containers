### RunPod NVIDIA PyTorch

**Official NVIDIA PyTorch containers optimized for RunPod.**

Built on NVIDIA's official PyTorch containers from NGC (NVIDIA GPU Cloud), these images provide the latest optimizations and features directly from NVIDIA, ready for immediate deployment on RunPod.

### What's included
- **NVIDIA optimized**: Built on official NVIDIA PyTorch containers with NGC optimizations
- **Latest PyTorch**: Uses PyTorch 2.5.1 (as specified in the 25.10 release) with full CUDA support
- **Zero setup**: PyTorch ready to import immediately, no additional installs required
- **GPU accelerated**: Full CUDA support with NVIDIA's latest optimizations
- **Developer friendly**: SSH server preconfigured for seamless remote development and debugging
- **Smart workspace**: Optimized directory structure and package caches for faster dependency installation
- **Jupyter ready (optional)**: Notebook and JupyterLab with widgets/extensions; enable by setting `JUPYTER_PASSWORD` (omit to disable)

### Available configurations
- **Base Image**: nvcr.io/nvidia/pytorch:25.10-py3
- **PyTorch**: 2.5.1 (from NGC 25.10 release)
- **Python**: 3.x (as provided by NVIDIA's base image)
- **CUDA**: As provided by NVIDIA's base image (typically latest stable)

### Why use NVIDIA's official containers?
NVIDIA's NGC PyTorch containers include:
- Latest performance optimizations from NVIDIA
- Pre-configured CUDA, cuDNN, and NCCL libraries
- Optimized for NVIDIA GPUs
- Regular updates with the latest features and bug fixes

### Usage
This image is designed to work seamlessly with RunPod's infrastructure:
- SSH access is automatically configured when you provide a PUBLIC_KEY
- Jupyter Lab starts automatically when you set a JUPYTER_PASSWORD
- NGINX proxy provides easy access to web services
- Persistent storage at `/workspace` for your data and models

Focus on your deep learning projects with the confidence of NVIDIA's optimized stack.

Please also see [../base/README.md](../base/README.md) for more details about the base RunPod features.

<div class="base-images">

## Generated Images

### NVIDIA PyTorch Images:
- Latest: `runpod/nvidia-pytorch:latest`
- Version tagged: `runpod/nvidia-pytorch:1.0.0-pytorch2510-py3`

</div>
