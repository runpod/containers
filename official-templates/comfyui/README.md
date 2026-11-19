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
tag's venv and fills it from the previous one: the packages are copied over at
the versions you had (hard links on the same volume, so it takes seconds and
no extra space), then your custom nodes' requirements are checked in one pass.
CUDA-specific packages (the ones above) and packages installed from a URL or
local path are removed from the copy. Node requirements that list them get
builds that match the new tag; ones you installed by hand need installing
again, and the startup log prints the command that lists them. The previous
venv is left in place so you can go back. If you are not going back, delete it
to free space.

This runs on every start where the tag's venv is missing. If you restore
`/workspace` from your own snapshot instead of using a network volume, take
the snapshot after one start on the new tag so that it includes the new venv.
Otherwise every pod repeats the migration.

If you used the `-cuda13.0` image before it had its own venv, your
`.venv-cu128` holds packages built for CUDA 13.0. Delete
`/workspace/runpod-slim/ComfyUI/.venv-cu128` before switching that volume to
`-cuda12.8`, so they are reinstalled for 12.8.

## Access

Every `/http` port is reachable by anyone who has the pod's proxy URL, so
each one needs a password. ComfyUI opens a first-run setup page if no password
has been configured. FileBrowser still requires its password variable. There
is no way to run either service without a password. Passwords are never
written to the pod log.

| port | service | password variable | without a password |
|---|---|---|---|
| `8188` | ComfyUI | `COMFYUI_PASSWORD` (optional, 12+ characters) | first-run setup page |
| `8080` | FileBrowser, rooted at `/workspace` | `FILEBROWSER_PASSWORD` (12+ characters) | not started |
| `8888` | JupyterLab, rooted at `/workspace` | `JUPYTER_PASSWORD` | not started, unless `JUPYTER_DISABLE_AUTH=true` |

- `22`: SSH, key only (set `PUBLIC_KEY`, or add an SSH key to your Runpod account). No root password is generated or logged.

### ComfyUI (`8188`)

ComfyUI has no login of its own, so it listens only inside the pod, and port
8188 is served by a small proxy that checks every request, including the
websocket the UI uses. On a fresh volume, open the `:8188` URL, read the
one-time setup code from the pod logs, and choose a password of at least 12
characters. ComfyUI stays closed until setup completes. Only a salted password
hash is saved at `/workspace/runpod-slim/.comfyui-auth` (mode `0600`); on a
network volume it survives redeployment with the same volume. A fresh volume
requires setup again. Never share the setup code or the pod logs containing it.

Existing deployments can keep using `COMFYUI_PASSWORD`. It takes precedence
over a saved hash. A configured password shorter than 12 characters is refused
and ComfyUI does not start.

- **Browser:** after setup, open the `:8188` URL. The browser asks for a username
  and password. Any username works; enter the password you chose. You can
  also open `https://<pod-id>-8188.proxy.runpod.net/?token=<password>`
  once to sign in without the prompt.
- **API clients:** send the password as `Authorization: Bearer <password>`
  or as an HTTP Basic password with any username, for example to
  `https://<pod-id>-8188.proxy.runpod.net/system_stats`.
  A request without it gets `401`.
- **Wrong passwords:** after 10 wrong passwords in a row, the proxy stops
  checking passwords and answers `429` until attempts slow to one a second.
  Browsers that are already signed in keep working.
- Web pages on another site cannot call this ComfyUI from a visitor's browser,
  even while that visitor is signed in. Opening a link to the UI from another
  site still works. Clients that are not browsers are not affected.

`--listen` and `--port` in `comfyui_args.txt` are ignored, with a warning in
the log, because the start script sets them.

ComfyUI-Manager's security settings are written on every start:
`security_level = normal`, `allow_git_url_install = False` and
`allow_pip_install = False`. Installing node packs from the registry works.
Installing from a git URL or a pip package name does not.

### FileBrowser (`8080`)

Sign in as `admin` with `FILEBROWSER_PASSWORD`. Without it, FileBrowser does
not start. FileBrowser requires at least 12 characters and rejects common
passwords. If yours is rejected, the log says so and FileBrowser does not
start. The admin password is reset to
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

ComfyUI starts without CORS headers, so pages on other websites cannot call it
from a browser. If your own site needs to, add
`--enable-cors-header https://your.site` here.

## SageAttention

The `-cuda12.8`, `-cuda13.0` and `-cuda13.2` images ship [SageAttention](https://github.com/thu-ml/SageAttention) 2.2.0, prebuilt for their exact PyTorch and CUDA by [runpod/sageattention](https://github.com/runpod/sageattention), so there is nothing to compile. It is off by default; to turn it on, add this line to `comfyui_args.txt` and restart the pod:

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

On any other GPU (B200, B300, V100, T4…) ComfyUI falls back to PyTorch attention, and the startup log warns about it. On an image without SageAttention, startup drops the flag with a warning rather than letting ComfyUI exit.

Do not `pip install sageattention` on top: the PyPI package is the older 1.x release, and it would shadow the prebuilt one. A SageAttention installed in the ComfyUI venv (by hand or by a custom node) always takes precedence over the pre-installed one; the startup log names it, and when it is older, gives the `pip uninstall` command that brings the pre-installed one back.

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.db`: FileBrowser DB
