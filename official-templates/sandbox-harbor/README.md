### Runpod Sandbox — Harbor

**[Harbor](https://www.harborframework.com/) preinstalled in a Runpod Sandbox.**

Harbor runs any agent, with any model, against any task, in parallel. This image is the harness side of a run: you drive evaluations from this sandbox, and each trial executes in its own environment. Harbor tasks carry their own environment images, so this template is not the image a trial runs inside.

### What's included
- **Harbor 0.23.0** (`harbor` on `PATH`), plus everything from the Ubuntu sandbox image: Python 3.14, `uv`, Node.js 24 and the usual build tooling.
- **tmux**, so a long evaluation survives a dropped connection.
- **sshd and sftp-server** installed but not running — the transport Harbor's Agent Sandbox Protocol speaks when it drives a remote sandbox.
- **Unprivileged by default**: commands run as `user` with passwordless `sudo` available.

### Running an evaluation

Harbor's default sandbox runtime is Docker, which is not available inside a sandbox — there are no nested containers here. Point it at a cloud provider instead and install the matching extra:

```bash
uv tool install 'harbor[daytona]'      # or [modal], [e2b], [novita], ...
harbor run -t hello-world/hello-world -a codex -m openai/gpt-5.6-luna -e <provider>
harbor view ./jobs
```

### Serving as an ASP target

To let a Harbor harness elsewhere drive *this* sandbox over SSH, generate host keys and start the daemon yourself:

```bash
sudo ssh-keygen -A
sudo mkdir -p /run/sshd && sudo /usr/sbin/sshd
```

You will also need to authorise a key in `~/.ssh/authorized_keys` and expose port 22 when creating the sandbox. Nothing starts sshd automatically: a sandbox has no service that needs it, and an unreachable daemon is only an attack surface.
