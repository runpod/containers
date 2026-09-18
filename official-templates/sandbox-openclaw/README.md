### Runpod Sandbox — OpenClaw

**[OpenClaw](https://docs.openclaw.ai/) running in a Runpod Sandbox.**

A sandbox for running the OpenClaw agent on isolated, disposable compute instead of your own machine. OpenClaw executes shell commands and edits files, so giving it a sandbox rather than a laptop is the point.

### What's included
- **OpenClaw 2026.9.4** with its bundled plugins, `openclaw` on `PATH`.
- **Node.js 24** with `npm` and `pnpm`, on Debian 12.
- **Python 3** with `pip`, plus `git`, `curl`, `jq`, `ripgrep`, an ssh client and the usual archive tools.
- **Unprivileged by default**: commands run as `node` with passwordless `sudo` available.

### Browser automation

No browser is baked in. A Chromium frozen into an image cannot be kept patched, and an agent driving it across the open web is exactly the traffic those patches are for. Install one when you need it, and you get the current build:

```bash
npx playwright install --with-deps chromium
```

Note that Chromium's own sandboxing relies on kernel features the isolation boundary restricts, so it may need to be launched without it.

### The gateway

The gateway starts with the container, bound to loopback, so the `openclaw` CLI works inside the sandbox from the first second.

It is not reachable from outside until you give it credentials — OpenClaw refuses to listen beyond loopback unauthenticated, and a sandbox is never claimed holding a token. To expose the Control UI on port **18789**, set a token and rebind, then request that port when creating the sandbox:

```bash
openclaw gateway restart --bind auto --token "$(openssl rand -hex 32)"
```

A sandbox never boots holding your credentials — they arrive once it is claimed — so the gateway comes up unconfigured. Run onboarding once, then restart the gateway so it picks them up:

```bash
# reads OPENAI_API_KEY and friends from the environment; --accept-risk is
# required with --non-interactive, since an agent gets full system access
openclaw onboard --non-interactive --accept-risk
openclaw gateway restart
```

Drop the two flags if you have a terminal attached and want the interactive flow.

State lives in `/home/node/.openclaw`, and the agent's working directory is `/home/node/.openclaw/workspace`.

### Notes
- OpenClaw's own Docker-based sandboxing is unavailable here: there is no Docker socket inside a sandbox, and the isolation boundary provides the containment instead.
- Install extra tooling at runtime with `sudo apt-get install` or `pip install`. For a heavier setup, build your own image on top of this one and register it as a sandbox template.
