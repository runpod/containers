### Runpod ROCm

**AMD GPU-accelerated images for PyTorch workloads.**

Built on our base images, these containers provide AMD GPU acceleration through ROCm and PyTorch. 

### What's included
- **ROCm ready**: AMD GPU compute platform (6.4.4) preconfigured for immediate use.
- **PyTorch accelerated**: Pre-installed and optimized for AMD GPU acceleration.
- **Complete toolkit**: Full development environment from our base images with Jupyter, SSH, and ML libraries.

### Available configurations
- **ROCm**: 6.4.4
- **PyTorch**: 2.5.1, 2.6.0, and 2.7.1
- **Ubuntu**: 22.04 (Jammy) and 24.04 (Noble)

Perfect for AMD GPU workloads with zero setup time.

**Note:** These images are significantly larger than our base images, so we provide a focused selection. Need additional combinations? Let us know!

## Generated Images

<div class="base-images">

### ROCm 6.4.4 Images:

**Ubuntu 22.04 (Python 3.10)** 
The venv must be activated with: `conda init && source ~/.bashrc && conda activate py_3.10`
- PyTorch 2.5.1: `runpod/base:1.0.2-rocm644-ubuntu2204-py310-pytorch251`
- PyTorch 2.6.0: `runpod/base:1.0.2-rocm644-ubuntu2204-py310-pytorch260`

**Ubuntu 24.04 (Python 3.12)** 
The venv must be activated with: `conda init && source ~/.bashrc && conda activate py_3.12`
- PyTorch 2.6.0: `runpod/base:1.0.2-rocm644-ubuntu2404-py312-pytorch260`
- PyTorch 2.7.1: `runpod/base:1.0.2-rocm644-ubuntu2404-py312-pytorch271`

</div>
