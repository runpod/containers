[![Watch the video](https://i3.ytimg.com/vi/JovhfHhxqdM/hqdefault.jpg)](https://www.youtube.com/watch?v=JovhfHhxqdM)

Run the latest ComfyUI with all dependencies pre-installed. On first boot, ComfyUI is copied to your workspace; it's ready when the logs show `ComfyUI is READY on port 8188`. ComfyUI-Manager keeps refreshing its node list for a few minutes after that; the UI does not wait for it.

pip's "A new release of pip is available" notice is turned off: pip is pinned in the image.

## Choosing a tag

```
runpod/comfyui:<release>-comfyui<comfyui version>-cuda<cuda version>
```

### ComfyUI version

| tag contains | ComfyUI |
|---|---|
| `-comfyuiv0.45.0` | 0.45.0 |
| `-comfyuiv0.44.0` | 0.44.0 |

Both have the same custom nodes and PyTorch. Pick `v0.45.0` for a new pod; `v0.44.0` is for workflows and custom nodes that have
not caught up yet.

Don't update ComfyUI inside a running pod; redeploy on the tag you want. Your
models, outputs, settings and custom nodes live on the volume and are kept,
in both directions.

### CUDA version

| tag ends in | PyTorch | use it on |
|---|---|---|
| `-cuda12.8` | 2.10.0, CUDA 12.8 | any GPU on a host with a 12.8 or newer driver |
| `-cuda13.0` | 2.10.0, CUDA 13.0 | hosts with a 13.0 or newer driver |
| `-cuda13.2` | 2.13.0, CUDA 13.2 | hosts with a 13.2 or newer driver; no Volta (V100) |

`-cuda13.2` is on a newer PyTorch because there is no CUDA 13.2 build older
than 2.12, and its torchaudio is the CPU build.

Pick `-cuda12.8` unless you need CUDA 13: a CUDA 13 pod will not start on a
host whose driver is older than the tag. The exception is datacenter GPUs (A40,
A100, H100, L40S…): there the image switches on NVIDIA's CUDA
forward-compatibility layer by itself and ComfyUI starts anyway. Consumer GPUs
(RTX 3090, RTX 5090…) don't support it. The `CUDA forward compat:` line in the
startup log says which case you are in; if it says `UNAVAILABLE`, redeploy on a
host with a newer driver. `DISABLE_CUDA_COMPAT=1` makes startup leave CUDA
setup alone: it neither switches the layer on nor removes it.

## Upgrading from a previous version

Pods created with the older (CUDA 12.4) template are migrated once, on the next
boot: ComfyUI and the bundled custom nodes move to the versions pinned in the
image, and the venv to the tag's CUDA version. Models, inputs, outputs,
settings and your own custom nodes are kept. The first start may take a few
extra minutes.

### The ComfyUI-Manager interface has changed

ComfyUI-Manager 4.x replaces the **Manager** button with the Nodes Manager built
into ComfyUI, opened from the **Extensions** icon at the top right of the
canvas. **Update ComfyUI** moved to the help menu (**?** at the bottom of the
sidebar); the image still refuses it, since the version belongs to the tag.
Snapshots have no screen in the new interface; the files and API endpoints
remain.

For the old interface, add `--enable-manager-legacy-ui` to
`/workspace/runpod-slim/comfyui_args.txt` and restart the pod. Settings,
snapshots and custom nodes carry over either way.

Installing from a git URL or a pip package is no longer governed by
`security_level`, but by `allow_git_url_install` and `allow_pip_install` (see
[ComfyUI access](#comfyui-8188)).

## Virtual environments on the volume

Packages installed at runtime (custom node requirements, your own
`pip install`) go into a per-CUDA venv on the volume:
`/workspace/runpod-slim/ComfyUI/.venv-cu128`, `.venv-cu130`, `.venv-cu132`.

When you switch a volume to another tag, the first start creates that tag's
venv from the previous one (hard links, so seconds and no extra space) and
re-checks your custom nodes' requirements. CUDA-specific packages (xformers,
triton, sageattention, onnxruntime-gpu, nunchaku) and packages installed from a
URL or path are dropped; node requirements get rebuilt for the new tag, and the
startup log prints the command listing hand-installed ones to reinstall. The
old venv is kept so you can go back; delete it to free space.

If you restore `/workspace` from your own snapshot rather than a network
volume, take it after one start on the new tag, or every pod repeats the
migration.

If you used `-cuda13.0` before it had its own venv, delete
`/workspace/runpod-slim/ComfyUI/.venv-cu128` before switching to `-cuda12.8`.

## Access

Every `/http` port is reachable by anyone with the pod's proxy URL, so each one
needs a password. Without its password a service does not start, and the pod
log says why. Passwords are never logged.

| port | service | password variable | without a password |
|---|---|---|---|
| `8188` | ComfyUI | `COMFYUI_PASSWORD` (12+ characters) | not started |
| `8080` | FileBrowser, rooted at `/workspace` | `FILEBROWSER_PASSWORD` (12+ characters) | not started |
| `8888` | JupyterLab, rooted at `/workspace` | `JUPYTER_PASSWORD` | not started, unless `JUPYTER_DISABLE_AUTH=true` |

- `22`: SSH, key only (set `PUBLIC_KEY`, or add an SSH key to your Runpod account). No root password is generated.

### ComfyUI (`8188`)

ComfyUI listens only inside the pod; port 8188 is a proxy that checks
`COMFYUI_PASSWORD` on every request, including the websocket.

- **Browser:** open the `:8188` URL and sign in with any username and
  `COMFYUI_PASSWORD`, or open `https://<pod-id>-8188.proxy.runpod.net/?token=<COMFYUI_PASSWORD>`
  once to skip the prompt.
- **API clients:** send `Authorization: Bearer <COMFYUI_PASSWORD>`, or Basic
  auth with any username. Without it: `401`.
- After 10 wrong passwords in a row, the proxy answers `429` until attempts
  slow to one a second. Signed-in browsers keep working.
- Pages on other sites cannot call this ComfyUI from a visitor's browser.
  Links to the UI still work, and non-browser clients are not affected.

`--listen` and `--port` in `comfyui_args.txt` are ignored with a warning.

ComfyUI-Manager is set on every start to `security_level = normal`,
`allow_git_url_install = False`, `allow_pip_install = False`: installing from
the registry works; from a git URL or pip package name does not.

### FileBrowser (`8080`)

[FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser). Sign in as
`admin` with `FILEBROWSER_PASSWORD`, which is reset on every start (this also
replaces the old `adminadmin12` default). The one-time "A new database was
created on startup" notice is expected on a new volume or after upgrading.

Upgrading from classic FileBrowser imports its users from `filebrowser.db` into
`filebrowser.sqlite` (both in `/workspace/runpod-slim`). Share links are not
carried over. Once it works, you can delete `filebrowser.db` and
`.filebrowser.json`. Models, inputs and outputs are not touched.

### JupyterLab (`8888`)

`JUPYTER_PASSWORD` is the login token; "Start Jupyter notebook" sets it for
you. With `JUPYTER_DISABLE_AUTH=true`, anyone with the URL gets a root shell.

## Pre-installed custom nodes

- ComfyUI-KJNodes
- Civicomfy
- ComfyUI-RunpodDirect

ComfyUI-RunpodDirect only takes download actions from the ComfyUI page: its
`POST` routes under `/server_download/` answer `403` to scripts that don't send
`Sec-Fetch-Site: same-origin`. `GET` routes such as `status` are unchanged. It
saves only into `ComfyUI/models` (after resolving symlinks, so
`extra_model_paths.yaml` targets or symlinks to a shared `/workspace/models`
get `400`) and refuses executable extensions (`.py`, `.sh`, `.so`…).

ComfyUI-Manager is the `comfyui_manager` pip package in the image, not a custom
node. An old copy under `custom_nodes` is ignored; the boot log says where it is.

## Custom Arguments

Edit `/workspace/runpod-slim/comfyui_args.txt` (one arg per line):

```
--max-batch-size 8
--preview-method auto
```

ComfyUI starts without CORS headers. If your own site needs to call it, add
`--enable-cors-header https://your.site`.

## SageAttention

All tags ship [SageAttention](https://github.com/thu-ml/SageAttention) 2.2.0, prebuilt by [runpod/sageattention](https://github.com/runpod/sageattention). It is off by default; add `--use-sage-attention` to `comfyui_args.txt` and restart.

| compute capability | GPUs |
|---|---|
| 8.0 | A100 |
| 8.6 | A40, RTX A6000, RTX 3090 |
| 8.9 | L40S, L4, RTX 4090, RTX 6000 Ada |
| 9.0 | H100, H200 |
| 12.0 | RTX 5090, RTX PRO 6000 Blackwell |

Other GPUs (B200, B300, V100, T4…) fall back to PyTorch attention with a warning.

Don't `pip install sageattention`: PyPI has the old 1.x, and any SageAttention in the ComfyUI venv takes precedence. The startup log names it and, if older, gives the `pip uninstall` command.

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/ComfyUI/user/__manager/config.ini`: ComfyUI-Manager settings
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.sqlite`: FileBrowser DB

## Source Code

[github.com/runpod/containers](https://github.com/runpod/containers/tree/main/official-templates/comfyui)
