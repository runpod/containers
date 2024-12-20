# Fast Stable Diffusion Template

This template provides a Fast Stable Diffusion environment with Automatic1111 Web UI.

## Features

- Automatic1111 Web UI
- Fast Stable Diffusion optimizations
- CUDA 11.8 support
- Python 3.10
- Jupyter Notebook support
- Dreambooth training support

## Included Models

The following models will be automatically mounted into the Pod:

- [Stable Diffusion XL Base 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/sd_xl_base_1.0.safetensors)
- [Stable Diffusion XL Refiner 1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0/blob/main/sd_xl_refiner_1.0.safetensors)
- [Stable Diffusion 1.5](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/blob/main/v1-5-pruned-emaonly.safetensors)
- [Stable Diffusion 2.1 (768)](https://huggingface.co/stabilityai/stable-diffusion-2-1/blob/main/v2-1_768-ema-pruned.ckpt)

## Usage Instructions

1. Connect to JupyterLab through port 8888
2. Open the RNPD-A1111.ipynb notebook
3. Run the notebook to start the Automatic1111 Web UI
4. Access the UI through port 3001

### Customizing Launch Parameters

You can modify the launch parameters in the "Start Stable-Diffusion" cell of the RNPD-A1111.ipynb notebook by editing this line:

```python
!python /workspace/sd/stable-diffusion-webui/webui.py $configf
```

### Using Custom Models

There are several ways to add your own models:

1. Using [runpodctl](https://github.com/runpod/runpodctl):

   - Install runpodctl following the [installation guide](https://github.com/runpod/runpodctl/blob/main/README.md)
   - Use runpodctl to upload your models to the pod
   - Place models in `/workspace/auto-models` directory

2. Cloud Storage Method:

   - Upload your models to Google Drive or other cloud storage
   - Download them to your pod using wget or curl
   - Move them to `/workspace/auto-models` directory

3. Direct Upload:
   - Use the JupyterLab interface to upload models
   - Navigate to `/workspace/auto-models` in JupyterLab
   - Upload your models directly through the interface

### Training with Dreambooth

1. Open one of the Dreambooth notebooks in JupyterLab
2. Follow the notebook instructions for training setup
3. Models trained with Dreambooth will be saved in the specified output directory

## Saving Your Work

### Uploading to Google Drive

1. Use [this colab notebook](https://colab.research.google.com/drive/1ot8pODgystx1D6_zvsALDSvjACBF1cj6) for Google Drive transfers
2. Run runpodctl through either:
   - Web terminal (found in pod connect menu)
   - Desktop terminal

### Local Backup

- Use runpodctl to download your files locally
- Important directories to backup:
  - `/workspace/auto-models` - Custom models
  - `/workspace/outputs` - Generated images
  - Any custom training data or fine-tuned models

## Important Notes

- This template doesn't support encrypted volumes
- The UI does not auto-launch on startup - you must start it through the notebook

## Network Ports

| Application      | Port | Type |
| ---------------- | ---- | ---- |
| Automatic1111 UI | 3001 | HTTP |
| Jupyter Notebook | 8888 | HTTP |
| SSH              | 22   | TCP  |

## Getting Help

For technical support, consider:

- [RunPod Community on Discord](https://discord.gg/cUpRmau42V)
- [Automatic1111 GitHub Issues](https://github.com/AUTOMATIC1111/stable-diffusion-webui/issues)
- [Stable Diffusion on Reddit](https://www.reddit.com/r/StableDiffusion/)
