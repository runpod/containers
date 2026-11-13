### Runpod Burn

**A GPU-ready environment for [Burn](https://github.com/tracel-ai/burn), the deep learning framework written in Rust.**

Built on our base images: SSH, JupyterLab, and the CUDA toolkit come from there. This image adds the Rust toolchain and a compiled Burn project, so you can run Burn on the GPU right after the pod starts.

### What's included

- **Rust**: Rust 1.100.0 with `rustfmt`, `clippy`, `rust-analyzer`, and `rust-src`. The toolchain lives in `/opt/rustup` and `/opt/cargo`, so mounting a volume on `/workspace` does not hide it.
- **Burn 0.22.1, already compiled**: `/opt/burn-starter` depends on Burn with the `cuda`, `vulkan`, `flex`, and `autodiff` features. It was built when the image was made, so the cargo registry already has Burn and its dependencies.
- **CUDA and Vulkan backends**: The CUDA backend uses the toolkit from the base image. The Vulkan backend (wgpu) needs the host's NVIDIA Vulkan driver. The image sets `NVIDIA_DRIVER_CAPABILITIES=all` so the container runtime mounts it, and adds a Vulkan ICD that loads the driver through EGL, because the GLX one the runtime mounts does not work without an X server. `vulkan-tools` is installed, so `vulkaninfo --summary` shows what the pod can see.
- **Rust in Jupyter**: [evcxr](https://github.com/evcxr/evcxr) is installed as a JupyterLab kernel.

### Getting started

Check that both GPU backends work:

```bash
cd /opt/burn-starter
cargo run --release           # both backends
cargo run --release -- cuda   # or just one
```

To start your own project on the persistent volume, copy the starter. The dependencies are already downloaded, but cargo compiles them again for the new project:

```bash
cp -r /opt/burn-starter /workspace/my-model
cd /workspace/my-model
cargo run --release
```

### Available configurations

- **Burn**: 0.22.1
- **CUDA**: 12.8.1, 12.9.0, 13.0.0, and 13.2.0. The tag says which toolkit the image has and which host driver it needs.
- **Ubuntu**: 24.04 (Noble)

### Links

- [Burn repository](https://github.com/tracel-ai/burn)
- [The Burn Book](https://burn.dev/books/burn/)
- [Burn examples](https://github.com/tracel-ai/burn/tree/main/examples)

Please also see [../base/README.md](../base/README.md)
