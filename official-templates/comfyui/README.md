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

Every `/http` port is reachable by anyone who has the pod's proxy URL, so
each one needs a password. All three web services work the same way: set the
password variable and the service requires it; set the `*_DISABLE_AUTH=true`
variable and it runs with no password; set neither and it does not start, and
the pod log says why. When both are set, the opt-out wins. Passwords are never
written to the pod log.

| port | service | password variable | opt-out |
|---|---|---|---|
| `8188` | ComfyUI | `COMFYUI_PASSWORD` | `COMFYUI_DISABLE_AUTH=true` |
| `8080` | FileBrowser, rooted at `/workspace` | `FILEBROWSER_PASSWORD` | `FILEBROWSER_DISABLE_AUTH=true` |
| `8888` | JupyterLab, rooted at `/workspace` | `JUPYTER_PASSWORD` | `JUPYTER_DISABLE_AUTH=true` |

- `22`: SSH, key only (set `PUBLIC_KEY`, or add an SSH key to your Runpod account). No root password is generated or logged.

### ComfyUI (`8188`)

ComfyUI has no login of its own. With `COMFYUI_PASSWORD` set, it listens only
inside the pod, and port 8188 is served by a small proxy that asks for the
password on every request, including the websocket the UI uses. The password
must be at least 12 characters; a shorter one counts as not set, and ComfyUI
does not start.

- **Browser:** open the `:8188` URL. The browser asks for a username and
  password. Any username works; the password is `COMFYUI_PASSWORD`. You can
  also open `https://<pod-id>-8188.proxy.runpod.net/?token=<COMFYUI_PASSWORD>`
  once to sign in without the prompt.
- **API clients:** send the password as `Authorization: Bearer <COMFYUI_PASSWORD>`
  or as an HTTP Basic password, for example
  `curl -u any:$COMFYUI_PASSWORD https://<pod-id>-8188.proxy.runpod.net/system_stats`.
  A request without it gets `401`.
- **Wrong passwords:** after 10 wrong passwords in a row, the proxy stops
  checking passwords and answers `429` until attempts slow to one a second.
  Browsers that are already signed in keep working.
- Web pages on another site cannot call this ComfyUI from a visitor's browser,
  even while that visitor is signed in. Opening a link to the UI from another
  site still works. Clients that are not browsers are not affected.

`COMFYUI_DISABLE_AUTH=true` serves ComfyUI directly on 8188 with no password.
Anyone with the URL can then run workflows on your GPU, and can install
custom nodes through ComfyUI-Manager. A custom node runs its own code on the
pod, so that gives them a shell, your files, and the pod's environment
variables.

`--listen` and `--port` in `comfyui_args.txt` are ignored, with a warning in
the log, because the start script sets them.

ComfyUI-Manager's security settings are written on every start:
`security_level = normal`, `allow_git_url_install = False` and
`allow_pip_install = False`. Installing node packs from the registry works.
Installing from a git URL or a pip package name does not.

### FileBrowser (`8080`)

Sign in as `admin` with `FILEBROWSER_PASSWORD`. FileBrowser requires at least
12 characters and rejects common passwords. If yours is rejected, the log says
so and FileBrowser does not start. The admin password is reset to
`FILEBROWSER_PASSWORD` on every start. This also replaces the `adminadmin12`
default that older versions of this image created.

### JupyterLab (`8888`)

`JUPYTER_PASSWORD` is the login token; deploying with "Start Jupyter notebook"
enabled sets it for you. This is the same behaviour as the pytorch and base
templates. With `JUPYTER_DISABLE_AUTH=true`, anyone with the URL gets a root
shell.

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

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.db`: FileBrowser DB
