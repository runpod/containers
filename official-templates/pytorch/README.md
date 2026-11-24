### Runpod PyTorch

**PyTorch-optimized images for deep learning workflows.**

Built on our base images, these containers provide pre-configured PyTorch and CUDA combinations for immediate deep learning development. Skip the compatibility guesswork and setup time: just run, and start training.

### What's included
- **Version matched**: PyTorch and CUDA combinations tested for optimal compatibility.
- **Zero setup**: PyTorch ready to import immediately, no additional installs required.
- **GPU accelerated**: Full CUDA support enabled for immediate deep learning acceleration.
- **Production ready**: Built on our stable base images with complete development toolchain.

### Available configurations
- **PyTorch**: 2.6.0, 2.7.1, 2.8.0, 2.9.0, 2.9.1, 2.12.0, 2.12.1, 2.13.0, and 2.15.0 (CUDA 13.0 and 13.2 only)
- **CUDA**: 12.8.1, 12.9.0, 13.0.0, and 13.2.0
- **Ubuntu**: 24.04 (Noble). 22.04 is no longer built: swap `ubuntu2204` for `ubuntu2404` in a pinned tag, keeping the same `cu`/`torch` parts. NVIDIA ships no Ubuntu 26.04 image for these CUDA versions yet.
- **Audio**: torchaudio is matched to each PyTorch version (2.11.0 on 2.12 and 2.13, 2.11.1 on 2.15). `torchaudio.load` and `save` are torchcodec wrappers from 2.9 on, so torchcodec ships in every 2.9 and later image. It is the CUDA build, so GPU video decoding through NVDEC works too — the replacement for `torchaudio.io`, which was removed in 2.9. On CUDA 13.2 torchaudio is the CPU build — see below.

### Recommended image: PyTorch 2.15

`runpod/pytorch:2.2.0-cu1300-torch2150-ubuntu2404` is the default image for Pods and Instant Clusters (the cluster variant is `runpod/pytorch-cluster:2.3.0-cu1300-torch2150-ubuntu2404`). It runs on any host with a CUDA 13 driver (580 or newer), the same hosts as the other CUDA 13.0 images, including Blackwell.

PyTorch 2.15 publishes only CUDA 13.2 and 13.4 wheels, so both 2.15 images (CUDA 13.0 and 13.2) carry the cu132 build. On the CUDA 13.0 image it runs through CUDA minor version compatibility: PyTorch brings its own CUDA 13.2.2 runtime libraries, and the system toolkit (`nvcc` 13.0) is only used to compile extensions. Use the CUDA 13.2 image if you build CUDA extensions and want the toolkit to match PyTorch exactly. It needs a driver that supports CUDA 13.2. 2.15 also drops Python 3.10, which these images no longer ship anyway.

What is new for distributed work:

- **Rewritten NCCL backend, now the default.** `init_process_group("nccl")` creates the new implementation (NCCL 2.30.7, from the `nvidia-nccl-cu13` wheel). It binds each process group to one device: pass `device_id=torch.device("cuda", local_rank)`, otherwise `LOCAL_RANK % device_count` is used. `nccl-lazy` gives each send/recv peer pair its own communicator, so point-to-point transfers to different peers can overlap. It also ships a flight recorder that dumps on hangs. Code that checks `isinstance(pg, ProcessGroupNCCL)` or calls legacy-only methods such as `comm_split_count()` needs `backend="nccl-legacy"` or `TORCH_DIST_USE_NCCL2=0` on every rank. Both are removed in the next PyTorch release.
- **NIXL backend for one-sided transfers.** `torch.distributed._transport` (experimental) moves tensors between processes without a matching receive, for example KV-cache transfer between prefill and decode workers in disaggregated inference. Its NIXL backend needs the `nixl` package, which PyTorch does not install, so these images ship `nixl` 1.5.2 with its CUDA 13 backend (`nixl-cu13`, bundled UCX):

  ```python
  from torch.distributed import _transport as transport
  t = transport.new_transport("nixl", device="cuda")  # plugin="UCX" by default
  ```

  Over InfiniBand/RoCE, use the `runpod/pytorch-cluster` image: it adds the RDMA user-space stack (`rdma-core`, `ibverbs-providers`) that UCX uses for the fabric.

### torchaudio on CUDA 13.2

On the CUDA 13.2 images with PyTorch 2.12 and 2.13, torchaudio is `2.11.0+cpu` rather than a CUDA build. PyTorch 2.15 is not affected: torchaudio 2.11.1 has a cu132 wheel, so both 2.15 images get the CUDA build.

torchaudio 2.11.0 has no cu132 wheel. The project stopped shipping alongside PyTorch after 2.11, and its one later release, 2.11.1, came out with PyTorch 2.15. The cu130 wheel is not a substitute: torchaudio compares the CUDA minor version at import and raises `RuntimeError` next to cu132 PyTorch. The `+cpu` wheel reports no CUDA, so the check passes.

Everything built out of PyTorch ops still runs on the GPU: `resample`, spectrograms, mel scale, filters, and the rest of `torchaudio.transforms`. Audio I/O is unaffected — from 2.9 on `torchaudio.load` and `save` go through torchcodec, which is the CUDA build in these images.

What is lost is the three features backed by torchaudio's own CUDA kernels:

- `torchaudio.functional.rnnt_loss` on CUDA tensors raises `NotImplementedError` (the CPU kernel is still registered).
- `torchaudio.functional.forced_align` on CUDA tensors, likewise.
- `CUCTCDecoder` / `cuda_ctc_decoder` imports, then fails when the decoder is constructed.

If you need any of these, use a CUDA 13.0 image: there PyTorch and torchaudio are both cu130 and the CUDA kernels are present.

### One copy of the CUDA libraries

The PyTorch wheels bring their own CUDA libraries as pip packages (`nvidia-cublas`, `nvidia-cudnn`, `nvidia-nccl`, ...), next to the ones the image already has in `/usr/local/cuda`. Where the image's copy is the same minor release with the same or a newer patch (cuDNN 9.10.2 for pip's 9.10.1, not 9.8 for pip's 9.5), the pip files under `site-packages/nvidia/` are symlinks to it, so the image does not store the CUDA runtime twice. PyTorch keeps the library versions it was released with; a newer minor release can change kernel choice and speed, so it is not substituted. The CUDA toolkit libraries switch together or not at all; cuDNN and NCCL each switch on their own. Any other pip library stays a regular file.

pip and uv still see every package as installed. `pip install --force-reinstall nvidia-cublas-cu12` (or any other of them) puts pip's own files back.

### Blackwell (B200, B300, RTX 50-series, RTX PRO 6000)

PyTorch 2.6.0 does not run on Blackwell in any image: it is built against CUDA 12.6, which predates the architecture, and the first tensor operation fails with `no kernel image is available for execution on the device`.

On CUDA 12.8 and 12.9, PyTorch 2.12.1 and 2.13.0 themselves work, but torchvision's CUDA operators do not. Those versions take their wheels from the cu129 index, whose torchvision is built without Blackwell, and no other CUDA 12 index can replace it: cu128 has no 2.12 or later build at all, and cu126 predates the architecture. The cu130 and cu132 wheels do support Blackwell, but they need a CUDA 13 driver — the hosts these images exist for do not have one.

PyTorch 2.8.0 has the same torchvision gap on CUDA 12.9, 13.0 and 13.2: there it also takes its wheels from the cu129 index. Only the CUDA 12.8 image uses cu128 for 2.8.0.

On Blackwell, use a CUDA 13.0 or 13.2 image with PyTorch 2.7.1, or 2.9.0 and later.

Focus on your models, not your environment setup.

Please also see [../base/README.md](../base/README.md)

<div class="base-images">

## Available PyTorch Images

### CUDA 12.8.1:
- Torch 2.6.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch291-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch2121-ubuntu2404`
- Torch 2.13.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1281-torch2130-ubuntu2404`

### CUDA 12.9.0:
- Torch 2.6.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch260-ubuntu2404`
- Torch 2.7.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch271-ubuntu2404`
- Torch 2.8.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch280-ubuntu2404`
- Torch 2.9.0:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch290-ubuntu2404`
- Torch 2.9.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch291-ubuntu2404`
- Torch 2.12.1:
  - Ubuntu 24.04: `runpod/pytorch:1.2.0-cu1290-torch2121-ubuntu2404`
- Torch 2.13.0:
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
- Torch 2.15.0 (default):
  - Ubuntu 24.04: `runpod/pytorch:2.2.0-cu1300-torch2150-ubuntu2404`

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
- Torch 2.15.0:
  - Ubuntu 24.04: `runpod/pytorch:2.2.0-cu1320-torch2150-ubuntu2404`

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