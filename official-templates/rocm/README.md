### Runpod ROCm

**AMD GPU-accelerated images for PyTorch workloads.**

Built on our base images, these containers provide AMD GPU acceleration through ROCm and PyTorch. 

### What's included
- **ROCm ready**: AMD GPU compute platform (6.4.4) preconfigured for immediate use.
- **PyTorch accelerated**: Pre-installed and optimized for AMD GPU acceleration.
- **Complete toolkit**: Full development environment from our base images with Jupyter, SSH, and ML libraries.

### Available configurations
- **ROCm**: 6.4.4
- **PyTorch**: 2.6.0 and 2.7.1
- **Ubuntu**: 24.04 (Noble). 22.04 is no longer built: for PyTorch 2.6.0 move to the `ubuntu2404-py312-pytorch260` tag, and use the `py_3.12` conda env in place of `py_3.10`. PyTorch 2.5.1 has no 24.04 build, so its last image is `runpod/rocm:1.4.0-rocm644-ubuntu2204-py310-pytorch251` (no further updates); upgrading to 2.6.0 or 2.7.1 is the supported path. AMD ships no ROCm 6.4.4 image for Ubuntu 26.04.

Perfect for AMD GPU workloads with zero setup time.

**Note:** These images are significantly larger than our base images, so we provide a focused selection. Need additional combinations? Let us know!

## Generated Images

<div class="base-images">

### ROCm 6.4.4 Images:

**Ubuntu 24.04 (Python 3.12)** 
The venv must be activated with: `conda init && source ~/.bashrc && conda activate py_3.12`
- PyTorch 2.6.0: `runpod/rocm:1.4.0-rocm644-ubuntu2404-py312-pytorch260`
- PyTorch 2.7.1: `runpod/rocm:1.4.0-rocm644-ubuntu2404-py312-pytorch271`

</div>
