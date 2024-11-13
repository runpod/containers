# Automatic1111 Stable Diffusion WebUI Template

A ready-to-use template for running Stable Diffusion WebUI (AUTOMATIC1111) on RunPod.

## Quick Start

1. Wait for the pod to fully initialize (GPU Utilization should be 0%)
2. Access the WebUI through port 3000
3. Start creating!

⚠️ **Note**: You may encounter a 502 error if you try to connect before initialization is complete.

## Pre-installed Models

The following models are automatically mounted and ready to use:

### Stable Diffusion Models

- [Stable Diffusion XL Base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/sd_xl_base_1.0.safetensors)
- [Stable Diffusion XL Refiner 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0/blob/main/sd_xl_refiner_1.0.safetensors)
- [Stable Diffusion 1.5](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/blob/main/v1-5-pruned-emaonly.safetensors)

### ControlNet Models

- Canny (control_v11p_sd15_canny.pth)

## Network Ports

| Application            | Port | Protocol | Description                         |
| ---------------------- | ---- | -------- | ----------------------------------- |
| Stable Diffusion WebUI | 3000 | HTTP     | Main interface for Stable Diffusion |
| Jupyter Lab            | 8888 | HTTP     | Python notebook interface           |
| SSH                    | 22   | TCP      | Secure shell access                 |

## Customization

### Modifying Launch Parameters

Launch parameters are configured in `webui-user.sh`. To modify them:

1. Edit the file in the workspace
2. Restart the pod to apply changes

Current default parameters include:

- `--xformers` for optimized memory usage
- `--listen` for network access
- `--enable-insecure-extension-access` for extension support

## Adding Custom Models

You have two options for adding your own models:

1. Using [runpodctl](https://github.com/runpod/runpodctl/blob/main/README.md)
2. Downloading from cloud storage (Google Drive, etc.)

## Backing Up Your Work

To save your work to Google Drive:

1. Use [this Google Colab notebook](https://colab.research.google.com/drive/1ot8pODgystx1D6_zvsALDSvjACBF1cj6)
2. Follow the instructions to transfer files using `runpodctl`

You can run `runpodctl` either through:

- The web terminal (in pod connect menu)
- The desktop terminal

## Important Notes

- This template doesn't support encrypted volumes
- For technical support, consider:
  - [RunPod Community on Discord](https://discord.gg/cUpRmau42V)
  - [Automatic1111 GitHub Issues](https://github.com/AUTOMATIC1111/stable-diffusion-webui/issues)
  - [Stable Diffusion on Reddit](https://www.reddit.com/r/StableDiffusion/)
