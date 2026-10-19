[![Watch the video](https://i3.ytimg.com/vi/JovhfHhxqdM/hqdefault.jpg)](https://www.youtube.com/watch?v=JovhfHhxqdM)

Run the latest ComfyUI with all dependencies pre-installed in the image. On first boot, ComfyUI is copied to your workspace — when you see `[ComfyUI-Manager] All startup tasks have been completed.` in the logs, it's ready to use.

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

### The ComfyUI-Manager interface has changed

ComfyUI-Manager 4.x replaces the old Manager interface with the Nodes Manager built
into ComfyUI. The familiar **Manager** button is gone, and so are the screens behind
it — installing and updating custom nodes now happens in the Nodes Manager, reached
from **Extensions** in the top bar.

Two things are not where they used to be. **Update ComfyUI** is now in the help menu —
the **?** icon at the bottom of the sidebar — rather than in the Manager. Snapshots have
no screen at all in the new interface; the files and the API endpoints are still there,
and the old interface still reads snapshots you saved before.

To get the old interface back, add this to `/workspace/runpod-slim/comfyui_args.txt` and
restart the pod:

```
--enable-manager-legacy-ui
```

Your settings, snapshots and installed custom nodes carry over either way — only the
interface changes.

Two smaller changes worth knowing about:

- Installing a custom node from a git URL, and installing a pip package from the
  Manager, are no longer governed by `security_level`. Manager 4.x moved them to
  `allow_git_url_install` and `allow_pip_install` in
  `ComfyUI/user/__manager/config.ini`, both off by default. If you had lowered
  `security_level` to use those features, set the flag you need instead.
- `network_mode` is set to `personal_cloud` on first boot. Manager 4.x refuses to
  install anything when ComfyUI listens on a public address, which a pod always does,
  and this is the setting that tells it the machine is yours. A value you chose
  yourself is left alone.

## Access

- `8188`: ComfyUI web UI
- `8080`: FileBrowser (admin / `FILEBROWSER_PASSWORD`, default: `adminadmin12`)
- `8888`: JupyterLab, rooted at `/workspace`. `JUPYTER_PASSWORD` is the login token; deploying with "Start Jupyter notebook" enabled sets it for you. Unset, JupyterLab does not start — same as the pytorch and base templates. `JUPYTER_DISABLE_AUTH=true` runs it with no password and takes precedence over `JUPYTER_PASSWORD`; the `:8888` proxy URL is public, so anyone with it gets a root shell.
- `22`: SSH (set `PUBLIC_KEY` or check logs for generated root password)

## Pre-installed custom nodes

- ComfyUI-KJNodes
- Civicomfy
- ComfyUI-RunpodDirect

ComfyUI-Manager is included too, but not as a custom node: it is the
`comfyui_manager` pip package installed in the image, which ComfyUI loads itself.
Pods created with an older template keep a copy under `custom_nodes`; ComfyUI
ignores it, and the boot log says where it is if you want the space back.

## Source Code

This is an open source template. Source code available at: [github.com/runpod/containers](https://github.com/runpod/containers/tree/main/official-templates/comfyui)

## Custom Arguments

Edit `/workspace/runpod-slim/comfyui_args.txt` (one arg per line):

```
--max-batch-size 8
--preview-method auto
```

ComfyUI-Manager runs from the `comfyui_manager` package installed in the image and
is started with `--enable-manager`. Add `--enable-manager-legacy-ui` here for the older
Manager interface, which is where the snapshot screens live.

## Directory Structure

- `/workspace/runpod-slim/ComfyUI`: ComfyUI install
- `/workspace/runpod-slim/ComfyUI/user/__manager/config.ini`: ComfyUI-Manager settings
- `/workspace/runpod-slim/comfyui_args.txt`: ComfyUI args
- `/workspace/runpod-slim/filebrowser.db`: FileBrowser DB
