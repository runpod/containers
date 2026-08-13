[![Watch the video](https://i3.ytimg.com/vi/JovhfHhxqdM/hqdefault.jpg)](https://www.youtube.com/watch?v=JovhfHhxqdM)

Run the latest ComfyUI with CUDA 12.8. All dependencies are pre-installed in the image. On first boot, ComfyUI is copied to your workspace — when you see `[ComfyUI-Manager] All startup tasks have been completed.` in the logs, it's ready to use.

> **This template is for CUDA 12 only.** It does not support CUDA 13 (Blackwell / RTX 5090).
> If you need CUDA 13, use our [ComfyUI CUDA 13 template](https://console.runpod.io/hub/template/comfyui-cuda-13?id=2lv7ev3wfp) instead.

## Upgrading from a previous version

If you have an existing pod created with an older version of this template (CUDA 12.4), a one-time migration is performed automatically on the next boot. ComfyUI and the bundled custom nodes are updated to the versions pinned by the image, while models, inputs, outputs, user settings, and user-installed custom nodes are preserved. The virtual environment is also migrated to CUDA 12.8 compatibility. This may take a few extra minutes on the first start after the update.

## Access

- `8188`: ComfyUI web UI
- `8080`: FileBrowser (admin / `FILEBROWSER_PASSWORD`, default: `adminadmin12`)
- `8888`: JupyterLab (token via `JUPYTER_PASSWORD`, root at `/workspace`)
- `22`: SSH (set `PUBLIC_KEY` or check logs for generated root password)

## Pre-installed custom nodes

- ComfyUI-Manager
- ComfyUI-KJNodes
- Civicomfy
- ComfyUI-RunpodDirect

## Source Code

This is an open source template. Source code available at: [github.com/runpod-workers/comfyui-base](https://github.com/runpod-workers/comfyui-base)

## Custom Arguments

Edit `/workspace/runpod-slim/comfyui_args.txt` (one arg per line):

```
--max-batch-size 8
--preview-method auto
```

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.db`: FileBrowser DB
