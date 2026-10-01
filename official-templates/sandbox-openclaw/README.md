### Runpod Sandbox — OpenClaw

**[OpenClaw](https://docs.openclaw.ai/) running in a Runpod Sandbox.**

A sandbox for running the OpenClaw agent on isolated, disposable compute instead of your own machine. OpenClaw executes shell commands and edits files, so giving it a sandbox rather than a laptop is the point.

### What's included
- **OpenClaw 2026.9.4** with its bundled plugins, `openclaw` on `PATH`.
- **Node.js 24** with `npm` and `pnpm`, on Debian 12.
- **Python 3** with `pip`, plus `git`, `curl`, `jq`, `ripgrep`, an ssh client and the usual archive tools.
- **Build tooling**: `build-essential`, for packages with native extensions.
- **`tmux`**, so a long-running command outlives the exec call that started it.
- **Unprivileged by default**: commands run as `node`.

### Browser automation

No browser is baked in. A Chromium frozen into an image cannot be kept patched, and an agent driving it across the open web is exactly the traffic those patches are for. Its shared libraries are, so installing one gets you the current build and it starts:

```bash
npx playwright install chromium
```

Leave `--with-deps` off. It shells out to `apt-get`, which needs a root a sandbox does not have, and the libraries it would install are already here.

Chromium's own sandboxing relies on kernel features the isolation boundary restricts, so launch it with `--no-sandbox`.

### The gateway

The gateway starts with the container, bound to loopback on port 18789, so the `openclaw` CLI works inside the sandbox from the first second.

The Control UI is not reachable from outside. A sandbox exposes no ports today, and the bind address is an argument to the gateway process, which is the container's own entry point rather than something you can change from a shell inside it. Drive the agent through `openclaw` over exec instead.

A sandbox never boots holding your credentials — they arrive once it is claimed — so the gateway comes up unconfigured. Run onboarding once:

```bash
# reads OPENAI_API_KEY and friends from the environment; --accept-risk is
# required with --non-interactive, since an agent gets full system access
openclaw onboard --non-interactive --accept-risk
```

Drop the two flags if you have a terminal attached and want the interactive flow. Note that `openclaw gateway restart` does not restart the gateway here: it manages a service definition, while in a sandbox the gateway is the container's entry point. If it has to come up with different credentials, create a new sandbox.

State lives in `/home/node/.openclaw`, and the agent's working directory is `/home/node/.openclaw/workspace`.

### Notes
- OpenClaw's own Docker-based sandboxing is unavailable here: there is no Docker socket inside a sandbox, and the isolation boundary provides the containment instead.
- Install extra tooling at runtime into your home directory: `pip install --user`, `npm install -g --prefix ~/.local`, or download a release archive and unpack it. System packages need a root a sandbox does not currently grant. For a heavier setup, build your own image on top of this one and register it as a sandbox template.
