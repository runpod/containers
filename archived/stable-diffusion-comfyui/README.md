This template provides [ComfyUI v0.3.10](https://github.com/comfyanonymous/ComfyUI/releases/tag/v0.3.10) (with ComfyUI Manager) with a couple of pre-installed models and Jupyter Lab.

## Models

The following models are already included:

- [FLUX.1 schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
- [Stable Diffusion XL Base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Stable Diffusion XL Refiner 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0)
- [Stable Diffusion 1.5](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive)
- [Stable Diffusion 2.1](https://huggingface.co/stabilityai/stable-diffusion-2-1)

## Custom Models

You can add your own models by placing them in the appropriate directories under `/workspace/comfyui/models/`:

- Checkpoints: `/workspace/comfyui/models/checkpoints/`
- VAE: `/workspace/comfyui/models/vae/`
- LoRA: `/workspace/comfyui/models/loras/`
- Controlnet: `/workspace/comfyui/models/controlnet/`
- Upscalers: `/workspace/comfyui/models/upscale_models/`
- Embeddings: `/workspace/comfyui/models/embeddings/`
- CLIP: `/workspace/comfyui/models/clip/`
- CLIP Vision: `/workspace/comfyui/models/clip_vision/`

These paths are configured in ComfyUI's `extra_model_paths.yml` file, so models placed in these directories will be automatically detected by ComfyUI.

> **Note:** data stored in `/workspace/comfyui` will be deleted when the Pod is deleted, unless you're using a [network volume](https://docs.runpod.io/pods/storage/create-network-volumes).

## Ports

| Application | Port | Type |
| ----------- | ---- | ---- |
| ComfyUI     | 3000 | HTTP |
| Jupyter Lab | 8888 | HTTP |
| SSH         | 22   | TCP  |

## Important Notes

- We automatically set the password for Jupyter Lab when creating the pod, but if you want to set it yourself, you have to do so via the `JUPYTER_PASSWORD` environment variable
- For technical support, consider:
  - [RunPod Community on Discord](https://discord.gg/cUpRmau42V)
  - [ComfyUI GitHub Issues](https://github.com/comfyanonymous/ComfyUI/issues)
