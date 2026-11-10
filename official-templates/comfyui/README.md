[![Watch the video](https://i3.ytimg.com/vi/JovhfHhxqdM/hqdefault.jpg)](https://www.youtube.com/watch?v=JovhfHhxqdM)

Run the latest ComfyUI with all dependencies pre-installed in the image. On first boot, ComfyUI is copied to your workspace — when you see `ComfyUI is READY on port 8188` in the logs, it's ready to use. ComfyUI-Manager keeps refreshing its node list for a few minutes after that; the UI does not wait for it, and neither should you.

pip's "A new release of pip is available" notice is turned off: pip is pinned in the image, so the notice is not something you need to act on.

## Choosing a tag

The image is published for three CUDA versions, and the tag says which one you get:

| tag ends in | PyTorch | use it on |
|---|---|---|
| `-cuda12.8` | 2.10.0, CUDA 12.8 | any GPU on a host with a 12.8 or newer driver |
| `-cuda13.0` | 2.10.0, CUDA 13.0 | hosts with a 13.0 or newer driver |
| `-cuda13.2` | 2.13.0, CUDA 13.2 | hosts with a 13.2 or newer driver; no Volta (V100) |

All three carry the same ComfyUI and the same custom nodes. `-cuda12.8` and
`-cuda13.0` differ only in the CUDA build; `-cuda13.2` is on a newer PyTorch,
because PyTorch has no CUDA 13.2 build older than 2.12. Its torchaudio is the
CPU build, since torchaudio was never published for CUDA 13.2.

Pick `-cuda12.8` unless you have a reason to want CUDA 13; a CUDA 13 pod will
not start on a host whose driver is older than the tag.

## Upgrading from a previous version

If you have an existing pod created with an older version of this template (CUDA 12.4), a one-time migration is performed automatically on the next boot. ComfyUI and the bundled custom nodes are updated to the versions pinned by the image, while models, inputs, outputs, user settings, and user-installed custom nodes are preserved. The virtual environment is also migrated to match the CUDA version of the tag you are now running. This may take a few extra minutes on the first start after the update.

## Virtual environments on the volume

Packages installed into ComfyUI at runtime (custom node requirements, anything
you `pip install` yourself) go into a venv on the volume, and each CUDA variant
has its own: `/workspace/runpod-slim/ComfyUI/.venv-cu128`, `.venv-cu130`,
`.venv-cu132`. Many of these packages (xformers, triton, sageattention,
onnxruntime-gpu, nunchaku) are built for one CUDA version, so the variants
cannot share them.

When you switch a volume to a different tag, the first start creates that
tag's venv and reinstalls the requirements of your custom nodes into it.
Packages you installed by hand are not carried over; the startup log prints
the command that lists them. The previous venv is left in place so you can go
back. If you are not going back, delete it to free space.

If you used the `-cuda13.0` image before it had its own venv, your
`.venv-cu128` holds packages built for CUDA 13.0. Delete
`/workspace/runpod-slim/ComfyUI/.venv-cu128` before switching that volume to
`-cuda12.8`, so they are reinstalled for 12.8.

## Access

- `8188`: ComfyUI web UI
- `8080`: FileBrowser (admin / `FILEBROWSER_PASSWORD`, default: `adminadmin12`)
- `8888`: JupyterLab, rooted at `/workspace`. `JUPYTER_PASSWORD` is the login token; deploying with "Start Jupyter notebook" enabled sets it for you. Unset, JupyterLab does not start — same as the pytorch and base templates. `JUPYTER_DISABLE_AUTH=true` runs it with no password and takes precedence over `JUPYTER_PASSWORD`; the `:8888` proxy URL is public, so anyone with it gets a root shell.
- `22`: SSH, key only (set `PUBLIC_KEY`, or add an SSH key to your Runpod account). No root password is generated or logged.

## Pre-installed custom nodes

- ComfyUI-Manager
- ComfyUI-KJNodes
- Civicomfy
- ComfyUI-RunpodDirect

## Source Code

This is an open source template. Source code available at: [github.com/runpod/containers](https://github.com/runpod/containers/tree/main/official-templates/comfyui)

## Custom Arguments

Edit `/workspace/runpod-slim/comfyui_args.txt` (one arg per line):

```
--max-batch-size 8
--preview-method auto
```

## SageAttention

The `-cuda12.8` and `-cuda13.0` images ship [SageAttention](https://github.com/thu-ml/SageAttention) 2.2.0, prebuilt for their exact PyTorch and CUDA, so there is nothing to compile. It is off by default; to turn it on, add this line to `comfyui_args.txt` and restart the pod:

```
--use-sage-attention
```

It has kernels for these GPUs:

| compute capability | GPUs |
|---|---|
| 8.0 | A100 |
| 8.6 | A40, RTX A6000, RTX 3090 |
| 8.9 | L40S, L4, RTX 4090, RTX 6000 Ada |
| 9.0 | H100, H200 |
| 12.0 | RTX 5090, RTX PRO 6000 Blackwell |

On any other GPU (B200, B300, V100, T4…) ComfyUI falls back to PyTorch attention, and the startup log warns about it. `-cuda13.2` does not include SageAttention yet; if the flag is set there, startup drops it with a warning rather than letting ComfyUI exit.

Do not `pip install sageattention` on top: the PyPI package is the older 1.x release, and it would shadow the prebuilt one.

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.db`: FileBrowser DB
