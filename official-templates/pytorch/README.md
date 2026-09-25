### Runpod PyTorch

**PyTorch-optimized images for deep learning workflows.**

Built on our base images, these containers provide pre-configured PyTorch and CUDA combinations for immediate deep learning development. Skip the compatibility guesswork and setup time: just run, and start training.

### What's included
- **Version matched**: PyTorch and CUDA combinations tested for optimal compatibility.
- **Zero setup**: PyTorch ready to import immediately, no additional installs required.
- **GPU accelerated**: Full CUDA support enabled for immediate deep learning acceleration.
- **Production ready**: Built on our stable base images with complete development toolchain.

### Available configurations
- **PyTorch**: 2.6.0, 2.7.1, 2.8.0, 2.9.0, 2.9.1, 2.12.0, 2.12.1, and 2.13.0
- **CUDA**: 12.8.1, 12.9.0, 13.0.0, and 13.2.0
- **Ubuntu**: 22.04 (Jammy) and 24.04 (Noble); CUDA 13.0.0 and 13.2.0 are 24.04 only
- **Audio**: torchaudio is matched to each PyTorch version (2.11.0, its last release, on 2.12 and 2.13). `torchaudio.load` and `save` are torchcodec wrappers from 2.9 on, so torchcodec ships in every 2.9 and later image. It is the CUDA build, so GPU video decoding through NVDEC works too — the replacement for `torchaudio.io`, which was removed in 2.9. On CUDA 13.2 torchaudio is the CPU build — see below.

### torchaudio on CUDA 13.2

On the CUDA 13.2 images with PyTorch 2.12 and 2.13, torchaudio is `2.11.0+cpu` rather than a CUDA build.

torchaudio's last release is 2.11.0, and no cu132 wheel exists or ever will — the project stopped shipping alongside PyTorch after 2.11. The cu130 wheel is not a substitute: torchaudio compares the CUDA minor version at import and raises `RuntimeError` next to cu132 PyTorch. The `+cpu` wheel reports no CUDA, so the check passes.

Everything built out of PyTorch ops still runs on the GPU: `resample`, spectrograms, mel scale, filters, and the rest of `torchaudio.transforms`. Audio I/O is unaffected — from 2.9 on `torchaudio.load` and `save` go through torchcodec, which is the CUDA build in these images.

What is lost is the three features backed by torchaudio's own CUDA kernels:

- `torchaudio.functional.rnnt_loss` on CUDA tensors raises `NotImplementedError` (the CPU kernel is still registered).
- `torchaudio.functional.forced_align` on CUDA tensors, likewise.
- `CUCTCDecoder` / `cuda_ctc_decoder` imports, then fails when the decoder is constructed.

If you need any of these, use a CUDA 13.0 image: there PyTorch and torchaudio are both cu130 and the CUDA kernels are present.

### Blackwell (B200, B300, RTX 50-series, RTX PRO 6000)

PyTorch 2.6.0 does not run on Blackwell in any image: it is built against CUDA 12.6, which predates the architecture, and the first tensor operation fails with `no kernel image is available for execution on the device`.

On CUDA 12.8 and 12.9, PyTorch 2.12.1 and 2.13.0 themselves work, but torchvision's CUDA operators do not. Those versions take their wheels from the cu129 index, whose torchvision is built without Blackwell, and no other CUDA 12 index can replace it: cu128 has no 2.12 or later build at all, and cu126 predates the architecture. The cu130 and cu132 wheels do support Blackwell, but they need a CUDA 13 driver — the hosts these images exist for do not have one.

On Blackwell, use a CUDA 13.0 or 13.2 image. Every PyTorch version there from 2.7.1 on is fully supported.

Focus on your models, not your environment setup.

Please also see [../base/README.md](../base/README.md)

<div class="base-images">

## Available PyTorch Images

### CUDA 12.8.1:
- Torch 2.6.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch260-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch271-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch280-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch290-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch291-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch291-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch2121-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch2121-ubuntu2404`
- Torch 2.13.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1281-torch2130-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch2130-ubuntu2404`

### CUDA 12.9.0:
- Torch 2.6.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch260-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch271-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch280-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch290-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch291-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch291-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch2121-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch2121-ubuntu2404`
- Torch 2.13.0:
  - Ubuntu 22.04: `runpod/pytorch:1.2.0-cu1290-torch2130-ubuntu2204`
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch2130-ubuntu2404`

### CUDA 13.0.0:
- Torch 2.6.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch291-ubuntu2404`
- Torch 2.12.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch2120-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch2121-ubuntu2404`
- Torch 2.13.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1300-torch2130-ubuntu2404`

### CUDA 13.2.0:
- Torch 2.6.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch291-ubuntu2404`
- Torch 2.12.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch2120-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch2121-ubuntu2404`
- Torch 2.13.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1320-torch2130-ubuntu2404`

<details>
  <summary> CUDA 12.4.1 (Legacy): </summary>
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
</details>
</div>