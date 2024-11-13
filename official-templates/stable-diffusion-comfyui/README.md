# ComfyUI Template

This template provides a ComfyUI environment.

## Included Models

The following models will be automatically mounted into the Pod:

- [Stable Diffusion XL Base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/sd_xl_base_1.0.safetensors)
- [Stable Diffusion XL Refiner 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0/blob/main/sd_xl_refiner_1.0.safetensors)
- [Stable Diffusion 1.5](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/blob/main/v1-5-pruned-emaonly.safetensors)
- [Stable Diffusion 2.1 (768)](https://huggingface.co/stabilityai/stable-diffusion-2-1/blob/main/v2-1_768-ema-pruned.ckpt)

## Features

- ComfyUI with ComfyUI Manager
- CUDA 11.8 support
- Python 3.10
- Jupyter Notebook support

## Network Ports

| Application      | Port | Type |
| ---------------- | ---- | ---- |
| ComfyUI Web UI   | 3000 | HTTP |
| Jupyter Notebook | 8888 | HTTP |
| SSH              | 22   | TCP  |

## Important Notes

- This template doesn't support encrypted volumes
- For technical support, consider:
  - [RunPod Community on Discord](https://discord.gg/cUpRmau42V)
  - [ComfyUI GitHub Issues](https://github.com/comfyanonymous/ComfyUI/issues)
  - [Stable Diffusion on Reddit](https://www.reddit.com/r/StableDiffusion/)
