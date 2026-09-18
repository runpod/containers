### Runpod Sandbox — Ubuntu

**The default environment for Runpod Sandboxes.**

A small, general purpose Ubuntu 26.04 image for running untrusted or agent-generated code. Creating a sandbox without naming a template or an image gives you this one.

### What's included
- **Ubuntu 26.04 LTS** (Resolute), pinned by digest so every sandbox starts from an identical filesystem.
- **Python 3.14** with `pip`, `venv` and [`uv`](https://docs.astral.sh/uv/) for fast installs.
- **Node.js 24 LTS** with `npm`.
- **Build tooling**: `build-essential`, `git`, `curl`, `wget`, `jq`, `ripgrep`, `unzip`, `zip`.
- **Unprivileged by default**: commands run as `user` (uid 1000) in `/home/user`, with passwordless `sudo` available.

### What's deliberately absent
No SSH server, no nginx and no Jupyter. Sandboxes execute commands through the Runpod API rather than through a service inside the container, and the isolation boundary rejects images that need privileged mode or host devices. If you want those, run a Pod instead.

### Usage

```python
from runpod import Sandbox

sandbox = Sandbox.create()          # uses this image
sandbox.exec("python --version")
```

To pin the image explicitly, pass `runpod/ubuntu:<version>-sandbox-ubuntu2604`.

### Extending it

Install what you need at runtime — `uv pip install`, `npm install`, or `sudo apt-get install`. For a heavier or repeatedly used environment, build your own image on top of this one and register it as a sandbox template.
