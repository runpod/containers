# ComfyUI

This template provides [ComfyUI v0.3.10](https://github.com/comfyanonymous/ComfyUI/releases/tag/v0.3.10) (with ComfyUI Manager) with a couple of pre-installed models and Jupyter Lab.

## Models

The following models are already included:

- [FLUX.1 schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
- [Stable Diffusion XL Base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Stable Diffusion XL Refiner 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0)
- [Stable Diffusion 1.5](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive)
- [Stable Diffusion 2.1](https://huggingface.co/stabilityai/stable-diffusion-2-1)

## Ports

| Application | Port | Type |
| ----------- | ---- | ---- |
| ComfyUI     | 3000 | HTTP |
| Jupyter Lab | 8888 | HTTP |
| SSH         | 22   | TCP  |

## Important Notes

- Jupyter Lab requires a password, set via `JUPYTER_PASSWORD` environment variable
- For technical support, consider:
  - [RunPod Community on Discord](https://discord.gg/cUpRmau42V)
  - [ComfyUI GitHub Issues](https://github.com/comfyanonymous/ComfyUI/issues)
