### Runpod Sandbox — Harbor

**[Harbor](https://www.harborframework.com/) preinstalled in a Runpod Sandbox.**

Harbor runs any agent, with any model, against any task, in parallel. This image is the harness side of a run: you drive evaluations from this sandbox, and each trial executes in its own environment. Harbor tasks carry their own environment images, so this template is not the image a trial runs inside.

### What's included
- **Harbor 0.23.0** (`harbor` on `PATH`), plus everything from the Ubuntu sandbox image: Python 3.14, `uv`, Node.js 24 and the usual build tooling.
- **tmux**, so a long evaluation outlives the exec call that started it.
- **An ssh client**, which is the half of Harbor's Agent Sandbox Protocol this side of a run needs.
- **Unprivileged by default**: commands run as `user`.

### Running an evaluation

Harbor's default sandbox runtime is Docker, which is not available inside a sandbox — there are no nested containers here. Point it at a cloud provider instead and install the matching extra:

```bash
uv tool install 'harbor[daytona]'      # or [modal], [e2b], [novita], ...
harbor run -t hello-world/hello-world -a codex -m openai/gpt-5.6-luna -e <provider>
harbor view ./jobs
```

### Why there is no sshd

A sandbox cannot serve as an Agent Sandbox Protocol target: exposed ports are reverse-proxied over HTTPS, so there is no inbound path for SSH to arrive on. Harbor only dials out from here, and that needs a client. If Harbor ever drives a Runpod sandbox as a trial environment, it will do so through the sandbox exec API rather than over SSH.
