"""SSH-based health and functional checks.

  * ssh_probe — one-shot connection probe, used as the real readiness signal
  * cuda_check_command / run_cuda_check — torch.cuda or nvidia-smi assertion
  * jupyter_check_command / run_jupyter_check — in-pod Jupyter probe over SSH
  * run_jupyter_proxy_check — public proxy probe from the test machine
  * pip_check / ca_certs / python_tls / uv / virtualenv command builders —
    opt-in image hygiene checks, all run through `run_simple_check`
 * REST API v2 log helpers / dump_pod_logs — diagnose failures before termination

Selection of the CUDA check is driven by the IMAGE REF, not the manifest
group name: new groups added in the future won't silently skip the check.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, NamedTuple, Optional

from . import api, config
from .log import log


# Error string returned by every helper that shells out to `ssh` and fails
# because the binary isn't on $PATH. Centralised so the message stays
# identical across helpers (callers grep for it in logs).
_SSH_BINARY_NOT_FOUND = "ssh binary not found"


# ---------------------------------------------------------------------------
# SSH plumbing
# ---------------------------------------------------------------------------


def _resolve_ssh_identity() -> Optional[str]:
    """Find the SSH private key to use for the runpodctl-managed PUBLIC_KEY.

    Order of preference:
      1. RUNPOD_SSH_KEY env var (explicit override)
      2. runpodctl-managed key at ~/.runpod/ssh/runpodctl-ssh-key
      3. Standard ssh defaults (~/.ssh/id_ed25519, ~/.ssh/id_rsa, ssh-agent)
    Returns the path if a non-default key was found, else None (let ssh
    pick a default from its standard search path / ssh-agent)."""
    if config.SSH_IDENTITY:
        return config.SSH_IDENTITY if os.path.isfile(config.SSH_IDENTITY) else None
    for candidate in (
        "~/.runpod/ssh/runpodctl-ssh-key",
        "~/.runpod/runpodctl-ssh-key",
        "~/.ssh/runpodctl-ssh-key",
    ):
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


class SshEndpoint(NamedTuple):
    """Everything needed to reach one pod over SSH.

    Passed by value rather than looked up in a registry: every pod's proxy
    lives at the same `ssh.runpod.io:22` and is told apart only by `user`,
    so anything keyed on (host, port) is a single global slot that parallel
    pods overwrite — and a check would then run against the wrong pod and
    still succeed, because the address it reached is a live pod.

    Direct SSH lands in the container as root. The proxy needs an opaque
    routing token and a pseudo-terminal, and the API hands us the exact
    invocation in `ssh.proxy.command`, so `command` carries that instead of
    us guessing the target.
    """

    host: str
    port: int
    user: str = "root"
    command: str = ""
    pty: bool = False

    @property
    def label(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"

    def __bool__(self) -> bool:
        return bool(self.host and self.port)


def _ssh_command_prefix(endpoint: SshEndpoint) -> list[str]:
    """Build the `ssh ... <user>@<host>` prefix common to all SSH calls.

    When the API gave us its own invocation, its target wins, with the flags
    its description tells us to add (`-i`, `-o StrictHostKeyChecking`) plus
    `-tt` for an endpoint that insists on a terminal.
    """
    identity = _resolve_ssh_identity()
    target = f"{endpoint.user}@{endpoint.host}"
    if endpoint.command:
        # Keep only the target from the API string: the flags we add below
        # are the ones it documents as missing, and re-using its argv
        # verbatim would fight with SSH_OPTS.
        parts = shlex.split(endpoint.command)
        target = next((p for p in parts[1:] if "@" in p), target)
    cmd = ["ssh", *config.SSH_OPTS]
    if endpoint.pty:
        # -tt, not -t: the local stdin is not a terminal under subprocess,
        # and single -t silently declines to allocate one in that case.
        cmd.append("-tt")
    if int(endpoint.port) != 22:
        cmd.extend(["-p", str(endpoint.port)])
    if identity:
        cmd.extend(["-i", identity])
    cmd.append(target)
    return cmd


def _strip_cr(text: str) -> str:
    """A PTY turns every \\n into \\r\\n; undo that so parsing and logs match
    what a direct, terminal-less connection would have produced."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


# RunPod's SSH proxy only hands out an interactive shell: a command given on
# the ssh command line is ignored and the session sits at a prompt until it
# is killed. So on a PTY endpoint the command is *typed* into that shell
# instead, base64-encoded so no quoting or heredoc can be mangled by the
# line editor, between two markers that carry the exit status back. Each
# marker is written split by quotes, so the terminal's echo of what we typed
# can never be mistaken for the marker itself.
_PTY_BEGIN = "__SMOKE_BEGIN__"
_PTY_RC_RE = re.compile(r"^__SMOKE_RC=(\d+)__$", re.MULTILINE)


def _pty_script(remote_cmd: str) -> str:
    """The keystrokes that run `remote_cmd` in an interactive shell."""
    b64 = base64.b64encode(remote_cmd.encode()).decode()
    return (
        f'echo "__SMOKE_""BEGIN__"; '
        f'bash -c "$(echo {b64} | base64 -d)" </dev/null 2>&1; '
        f'echo "__SMOKE_""RC=$?__"; exit\n'
    )


def _pty_result(stdout: str) -> tuple[Optional[int], str]:
    """(exit status, output) from a PTY session; status is None when the
    command never finished (no RC marker), output is what it printed."""
    text = _strip_cr(stdout)
    begin = text.rfind(_PTY_BEGIN + "\n")
    body = text[begin + len(_PTY_BEGIN) + 1:] if begin >= 0 else text
    m = _PTY_RC_RE.search(body)
    if m is None:
        return None, body
    return int(m.group(1)), body[:m.start()]


def _run_pty(argv: list[str], keys: str, timeout: float) -> tuple[int, str, str]:
    """Type `keys` into an interactive session and wait for it to end.

    stdin stays open until the session closes itself (our script ends with
    `exit`): an EOF can reach the remote terminal as ^D, and an interactive
    shell that sees ^D before it has read the line logs out without running
    it. Raises TimeoutExpired / FileNotFoundError like subprocess.run.
    """
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    out: list[str] = []
    err: list[str] = []
    readers = [
        threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True),
        threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True),
    ]
    for t in readers:
        t.start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(keys)
        proc.stdin.flush()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    except BrokenPipeError:
        proc.wait(timeout=timeout)   # the session ended before reading
    finally:
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    for t in readers:
        t.join(timeout=5)
    return proc.returncode, "".join(out), "".join(err)


def run_ssh(
    endpoint: SshEndpoint, remote_cmd: str, timeout: float,
) -> subprocess.CompletedProcess:
    """Run `remote_cmd` on the pod; same contract as `subprocess.run`
    (raises TimeoutExpired / FileNotFoundError), with stdout already CR-free.

    stdin is never inherited: an `ssh -tt` holding the caller's terminal
    switches it to raw mode and, when killed by the timeout, leaves it there.
    """
    prefix = _ssh_command_prefix(endpoint)
    if not endpoint.pty:
        r = subprocess.run(
            [*prefix, remote_cmd], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
        return subprocess.CompletedProcess(
            r.args, r.returncode, _strip_cr(r.stdout), r.stderr,
        )
    ssh_rc, stdout, stderr = _run_pty(prefix, _pty_script(remote_cmd), timeout)
    rc, out = _pty_result(stdout)
    if rc is None:
        # The session ended without the command finishing: a refused or
        # dropped connection. Keep ssh's own status and words for the log.
        return subprocess.CompletedProcess(
            prefix, ssh_rc or 255, "", (stderr or out).strip(),
        )
    return subprocess.CompletedProcess(prefix, rc, out, stderr if rc else "")


def ssh_probe(endpoint: SshEndpoint, timeout: int = 8) -> tuple[bool, str]:
    """One-shot SSH connection attempt. Returns (success, stderr_excerpt).
    Used as the real container-readiness signal."""
    try:
        r = run_ssh(endpoint, "echo ready", timeout)
    except subprocess.TimeoutExpired:
        return False, "ssh probe timed out"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    if r.returncode == 0 and "ready" in r.stdout:
        return True, ""
    return False, (r.stderr or r.stdout).strip()[:200]


# ---------------------------------------------------------------------------
# CUDA / GPU functional check
# ---------------------------------------------------------------------------

# Image-tag substrings/patterns we treat as "this image expects a GPU
# runtime" (NVIDIA CUDA or AMD ROCm). Kept loose on purpose — the worst
# case for a false positive is running nvidia-smi on a CPU pod, which just
# returns non-zero and surfaces as a FAIL we'd want to see anyway.
_GPU_TAG_RE = re.compile(
    # 'cuda1281', 'cuda1300', or the bare word 'cuda' (e.g. nvidia/cuda:...)
    r"\bcuda\b|\bcuda\d"
    # 'cu1281', 'cu1290' short form. Boundary prevents matching 'cube',
    # 'cute', etc. — we require a digit immediately after 'cu'.
    r"|(?:^|[^a-z0-9])cu\d"
    # AMD ROCm tag fragments: 'rocm', 'rocm644'.
    r"|\brocm",
    re.IGNORECASE,
)

# Image-name/tag markers that imply PyTorch is installed in the *system*
# Python (i.e. `python -c "import torch"` will work over SSH).
# Deliberately does NOT match autoresearch: its torch lives in
# /opt/autoresearch/.venv (uv-managed) and isn't on sys.path for the
# system interpreter we ssh into.
_TORCH_TAG_RE = re.compile(
    # 'pytorch' anywhere in name or tag covers runpod/pytorch,
    # runpod/nvidia-pytorch, and base images with -pytorch251-style tags.
    r"\bpytorch"
    # Tag fragments like 'torch260', 'torch271' — short form some images use.
    r"|(?:^|[^a-z0-9])torch\d",
    re.IGNORECASE,
)

# Image-tag markers for AMD ROCm runtimes. Matched BEFORE the torch regex
# so that ROCm-pytorch images (which inherit from rocm/pytorch:* and keep
# torch in a conda env not visible to the system `python`) take the
# rocm-smi path instead of falling into the import-torch path and failing
# with a misleading "ModuleNotFoundError".
_ROCM_TAG_RE = re.compile(r"\brocm", re.IGNORECASE)

# Appended to the torch check for groups that opted in with
# `test_torch_packages`. These three come from their own wheel indexes and
# carry compiled extensions pinned to one torch and CUDA version, so a
# mismatch only surfaces on import or first use.
_TORCH_PACKAGES_PROGRAM = (
    "import torchvision\n"
    "boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 11., 11.]], device='cuda')\n"
    "keep = torchvision.ops.nms(boxes, torch.tensor([0.9, 0.8], device='cuda'), 0.5)\n"
    "assert keep.tolist() == [0], f'nms kept {keep.tolist()}, expected [0]'\n"
    "print(f'torchvision={torchvision.__version__} nms ok')\n"
    "import torchaudio\n"
    "wav = torch.sin(torch.arange(16000, device='cuda', dtype=torch.float32) / 20)\n"
    "out = torchaudio.functional.resample(wav.unsqueeze(0), 16000, 8000)\n"
    "assert out.shape == (1, 8000), f'resample gave {tuple(out.shape)}'\n"
    "assert out.is_cuda, f'resample returned a {out.device} tensor'\n"
    "print(f'torchaudio={torchaudio.__version__} resample ok')\n"
    # The images ship torchcodec from torch 2.9 on, so gate on that rule
    # rather than on whether the import happens to work. The round trip also
    # covers the system FFmpeg torchcodec loads against.
    "major, minor = (int(p) for p in torch.__version__.split('+')[0].split('.')[:2])\n"
    "if (major, minor) < (2, 9):\n"
    "    print(f'torchcodec: not shipped for torch {torch.__version__}')\n"
    "else:\n"
    "    import torchcodec\n"
    "    from torchcodec.decoders import AudioDecoder\n"
    "    from torchcodec.encoders import AudioEncoder\n"
    "    encoded = AudioEncoder(wav.unsqueeze(0).cpu(), sample_rate=16000).to_tensor('wav')\n"
    "    samples = AudioDecoder(encoded).get_all_samples()\n"
    "    assert samples.sample_rate == 16000, f'decoded at {samples.sample_rate} Hz'\n"
    "    assert samples.data.shape == (1, 16000), f'decoded {tuple(samples.data.shape)}'\n"
    "    print(f'torchcodec={torchcodec.__version__} wav round trip ok')\n"
)


def _image_expects_gpu(image: str) -> bool:
    """True if the image ref implies a GPU runtime (CUDA or ROCm) inside."""
    return bool(_GPU_TAG_RE.search(image))


def _image_expects_torch(image: str) -> bool:
    """True if the image ref implies PyTorch is importable from system Python."""
    return bool(_TORCH_TAG_RE.search(image))


def _image_expects_rocm(image: str) -> bool:
    """True if the image ref implies an AMD ROCm runtime."""
    return bool(_ROCM_TAG_RE.search(image))


def fetch_pod_cuda_version(pod_id: str, attempts: int = 3) -> str:
    """Return the CUDA version the host reported, e.g. '13.0'.

    `min_cuda_version` is only a floor, so the scheduler may place the pod on
    any host at or above it — this reports what it actually got, which is the
    point of a compatibility matrix.

    Nullable per the API: CPU pods and hosts that never reported one give ''.
    Retried a few times because the value only lands once the scheduler has
    assigned a machine. Reporting only — never turns a PASS into a FAIL.
    """
    for attempt in range(1, attempts + 1):
        status, data = api.request("GET", f"/pods/{pod_id}", timeout=15)
        cuda = data.get("cudaVersion") if isinstance(data, dict) else None
        if 200 <= status < 300 and cuda:
            return str(cuda).strip()
        if attempt < attempts:
            time.sleep(2)
    return ""


def cuda_check_command(image: str, torch_packages: bool = False) -> str:
    """Return a shell command that functionally validates the GPU/CUDA stack
    for a given image, or '' to skip the check (CPU images).

    `torch_packages` (the group's `test_torch_packages` field) adds
    torchvision, torchaudio and torchcodec ops, and requires them.

    Selection is driven by the IMAGE REF (not the manifest group name) so
    new manifest groups added in the future won't silently skip the check.

    Logic (first match wins):
        - has 'rocm' in ref                          -> run rocm-smi check
          (AMD GPUs; runpod/base ROCm-pytorch images inherit from
          rocm/pytorch:* where torch lives in a conda env not visible to
          the system `python`, so the torch.cuda path would falsely fail
          with ModuleNotFoundError)
        - has 'pytorch' / 'torch\\d' in ref          -> run torch.cuda check
          (covers runpod/pytorch, runpod/nvidia-pytorch — NVIDIA stack),
          plus torchvision, torchaudio and torchcodec when
          `torch_packages` is set
        - has 'cuda' / 'cu\\d' only                  -> run nvidia-smi check
          (runpod/base GPU tags and autoresearch — torch in venv not
          visible to system python)
        - none of the above                          -> CPU image, no check

    The returned command MUST exit non-zero on failure so the SSH call can
    detect it. Output is captured for the run report.
    """
    if _image_expects_rocm(image):
        # AMD ROCm path. `rocm-smi` is the AMD counterpart to nvidia-smi
        # and ships in every official rocm/* base image. We assert it
        # finds at least one GPU by grepping for the GPU table header.
        return (
            "set -e; "
            "rocm-smi --showproductname --showmeminfo vram; "
            "rocm-smi --showid | grep -qE '^GPU\\[[0-9]+\\]' "
            "  || { echo 'FAIL: rocm-smi reported no GPUs'; exit 1; }; "
            "if command -v hipcc >/dev/null; then "
            "  hipcc --version | head -n 2; "
            "else "
            "  echo 'hipcc not in PATH (HIP toolkit may be runtime-only)'; "
            "fi"
        )

    if _image_expects_torch(image):
        # Use `python` (the runpod/base symlink /usr/local/bin/python ->
        # /usr/bin/python3.12), NOT `python3`. On Ubuntu 22.04 system
        # `python3` resolves to python3.10 — but pytorch/Dockerfile
        # installs torch via `python -m pip`, so torch only exists in
        # python3.12's site-packages. On 24.04 they happen to coincide.
        # Using `python` is portable.
        program = (
            "import sys, torch\n"
            "assert torch.cuda.is_available(), 'torch.cuda.is_available() returned False'\n"
            "n = torch.cuda.device_count()\n"
            "assert n > 0, 'torch.cuda.device_count() == 0'\n"
            "name = torch.cuda.get_device_name(0)\n"
            "cap = torch.cuda.get_device_capability(0)\n"
            "print(f'torch={torch.__version__} cuda={torch.version.cuda} '\n"
            "      f'gpus={n} dev0={name!r} compute={cap[0]}.{cap[1]}')\n"
            "# Tiny tensor-on-GPU sanity check: catches driver bugs that pass\n"
            "# is_available() but fail on actual memory ops.\n"
            "x = torch.ones(64, 64, device='cuda')\n"
            "y = (x @ x).sum().item()\n"
            "assert y == 64*64*64, f'matmul gave {y}, expected {64*64*64}'\n"
            "print('matmul ok')\n"
        )
        if torch_packages:
            program += _TORCH_PACKAGES_PROGRAM
        return f"python - <<'PY'\n{program}PY"

    if _image_expects_gpu(image):
        # GPU image without system-Python torch (raw base, autoresearch's
        # uv-venv'd torch, etc.). Verify the toolkit + driver respond to a
        # real query — more than just an nvidia-smi banner.
        return (
            "set -e; "
            "nvidia-smi -L; "
            "nvidia-smi --query-gpu=name,driver_version,memory.total "
            "  --format=csv,noheader; "
            "if command -v nvcc >/dev/null; then "
            "  nvcc --version | tail -n 2; "
            "else "
            "  echo 'nvcc not in PATH (CUDA toolkit may be runtime-only)'; "
            "fi"
        )

    # No GPU/torch markers — treat as CPU image. Boot + dwell is the only
    # gate; no extra functional check to run.
    return ""


def run_cuda_check(
    endpoint: SshEndpoint, image: str, torch_packages: bool = False,
) -> tuple[bool, str]:
    """Run the GPU/CUDA functional check inside the pod over SSH.
    Returns (ok, output). ok=True when:
      * the image has no GPU check defined (treated as pass), OR
      * the remote command exits 0.
    output contains stdout+stderr for inclusion in the run log."""
    cmd = cuda_check_command(image, torch_packages)
    if not cmd:
        return True, "(no GPU check for this image)"
    try:
        r = run_ssh(endpoint, cmd, 90)
    except subprocess.TimeoutExpired:
        return False, "cuda check timed out after 90s"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    combined = _strip_cr(r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


# ---------------------------------------------------------------------------
# Image hygiene checks (opt-in)
#
# Each builds a command that exits non-zero on failure and is run by
# `run_simple_check` over SSH. All of them are manifest opt-ins rather than
# auto-detected: an image that cannot satisfy one must say so by leaving the
# flag off, so a missing interpreter reads as a config decision and not as a
# silently skipped check.
# ---------------------------------------------------------------------------


# CA roots that must not be trusted anywhere, named one per entry and
# matched case-insensitively against certificate subjects.
#
# Name the individual root, not the family. Distrust is decided per root:
# Ubuntu's ca-certificates ships emSign ECC Root CA - G3 disabled while
# still trusting C1, C3 and G1, so a bare 'emSign' would fail on three
# roots nobody has revoked. Groups can override with `revoked_ca_names:`.
REVOKED_CA_NAMES: tuple[str, ...] = (
    # CON-1869 / CVE-2026-111943.
    "emSign ECC Root CA - G3",
)


def _sh_quote_list(values: tuple[str, ...] | list[str]) -> str:
    """Render values as a space-separated list of single-quoted shell words,
    for interpolation into a `for name in ...` loop."""
    return " ".join(shlex.quote(v) for v in values)


# Fetch a real HTTPS endpoint through whichever trust store is in play. Kept
# as two statements rather than `curl ... && echo ...`: under `set -e` a
# failing left side of an AND-list is exempt, so the && form would let a
# broken trust store reach the final `exit 0`.
_TLS_PROBE = (
    # HEAD, not GET: this only has to validate the TLS chain against the
    # trust store, and pypi.org/simple/ is a ~50MB index that times out on a
    # slow pod if downloaded in full.
    "curl -fsS --max-time 30 -I https://pypi.org/simple/ -o /dev/null; "
    "echo 'https fetch ok'"
)

# Every `uv` reachable on $PATH, one per line, in $FOUND.
#
# The `if` is load-bearing. With `[ -x ... ] && echo`, the loop's exit status
# is the last iteration's test, so a $PATH whose final entry has no uv makes
# the whole command substitution exit 1 and `set -e` kills the check before
# it reports anything. An `if` with no `else` returns 0 instead.
_UV_PATH_SCAN = (
    # Resolve each hit to its canonical path and dedupe: on a usr-merged
    # image /bin is a symlink to /usr/bin, so one uv shows up under both PATH
    # entries. Distinct binaries have distinct realpaths and still both count.
    "FOUND=$(printf '%s' \"$PATH\" | tr ':' '\\n' | while read -r d; do "
    "  if [ -n \"$d\" ] && [ -x \"$d/uv\" ]; then "
    "    readlink -f \"$d/uv\" 2>/dev/null || echo \"$d/uv\"; "
    "  fi; "
    "done | sort -u)"
)


def pip_check_command(allowed: tuple[str, ...] | list[str] = ()) -> str:
    """Run `pip check` and fail on any conflict that isn't in `allowed`.

    `allowed` holds substrings of accepted conflict lines (manifest field
    `pip_check_allow`), for pre-existing conflicts inherited from a vendor
    base image that we have decided not to carry as a red build. Anything
    else — including a new conflict introduced by bumping a pinned
    dependency — fails.
    """
    program = (
        "import subprocess, sys\n"
        f"allowed = {list(allowed)!r}\n"
        "r = subprocess.run([sys.executable, '-m', 'pip', 'check'],\n"
        "                   capture_output=True, text=True)\n"
        "out = (r.stdout + r.stderr).strip()\n"
        "print(out or '(pip check produced no output)')\n"
        "bad = [ln for ln in out.splitlines()\n"
        "       if ln.strip()\n"
        "       and not ln.startswith('No broken requirements')\n"
        "       and not any(a in ln for a in allowed)]\n"
        "if bad:\n"
        "    print('FAIL: unexpected dependency conflicts:')\n"
        "    for ln in bad:\n"
        "        print('  ' + ln)\n"
        "    sys.exit(1)\n"
        "print(f'pip check ok ({len(allowed)} known conflict(s) allowed)')\n"
    )
    return f"python - <<'PY'\n{program}PY"


def ca_certs_check_command(
    revoked: tuple[str, ...] | list[str] = REVOKED_CA_NAMES,
    min_version: str = "",
) -> str:
    """Verify the SYSTEM trust store: the patched `ca-certificates` package
    is installed, no revoked root is still trusted, and an HTTPS fetch
    against the store succeeds.

    Deliberately shell-only — sandbox images may ship no Python, and the
    system store is what curl, apt and git use. The certifi bundle that
    Python reaches for is a separate store with its own check below.

    `min_version` is the floor for the installed package, compared with
    `dpkg --compare-versions`. It is the direct check: the images ship
    whatever distrust decision the distro published, so what we assert is
    that the published package actually arrived. Without it, an
    `apt-get install --only-upgrade ca-certificates` that found nothing to
    upgrade exits 0 and the image looks patched when it is not.
    """
    version_gate = (
        "VER=$(dpkg-query -W -f='${Version}' ca-certificates 2>/dev/null "
        "  || true); "
        f"MIN={shlex.quote(min_version)}; "
        "if [ -z \"$VER\" ]; then "
        "  echo 'FAIL: ca-certificates is not installed via dpkg'; exit 1; "
        "fi; "
        "if dpkg --compare-versions \"$VER\" ge \"$MIN\"; then "
        "  echo \"ca-certificates $VER >= $MIN\"; "
        "else "
        "  echo \"FAIL: ca-certificates $VER is older than $MIN — "
        "the patched package did not reach this image\"; exit 1; "
        "fi; "
    ) if min_version else ""
    return (
        # pipefail: the subject scan below pipes openssl into openssl; without
        # it a failed openssl leaves an empty list and every root reads absent.
        "set -e; set -o pipefail; "
        "echo \"ca-certificates: "
        "$(dpkg-query -W -f='${Version}' ca-certificates 2>/dev/null "
        "  || echo 'not installed via dpkg')\"; "
        f"{version_gate}"
        "BUNDLE=/etc/ssl/certs/ca-certificates.crt; "
        "test -s \"$BUNDLE\" "
        "  || { echo \"FAIL: $BUNDLE missing or empty\"; exit 1; }; "
        "echo \"trusted roots: $(grep -c 'BEGIN CERTIFICATE' \"$BUNDLE\")\"; "
        # Subjects, so a revoked root is matched by name and not by the
        # base64 body. Without openssl, fall back to the per-cert symlink
        # names that update-ca-certificates maintains.
        # Underscores become spaces so one spelling of a root name matches
        # both forms: openssl prints 'CN=emSign Root CA - G1', while the
        # filename fallback has 'emSign_Root_CA_-_G1.pem'.
        "if command -v openssl >/dev/null 2>&1; then "
        "  openssl crl2pkcs7 -nocrl -certfile \"$BUNDLE\" "
        "    | openssl pkcs7 -print_certs -noout "
        "    | tr '_' ' ' > /tmp/ca-subjects.txt; "
        "else "
        "  echo 'openssl not present — matching on /etc/ssl/certs names'; "
        "  ls /etc/ssl/certs | tr '_' ' ' > /tmp/ca-subjects.txt; "
        "fi; "
        "rc=0; "
        f"for name in {_sh_quote_list(revoked)}; do "
        "  if grep -qi -- \"$name\" /tmp/ca-subjects.txt; then "
        "    echo \"FAIL: revoked CA still trusted: $name\"; rc=1; "
        "  else "
        "    echo \"revoked CA absent: $name\"; "
        "  fi; "
        "done; "
        # A trust store can also be broken by over-pruning, so prove it
        # still validates a real endpoint before reporting success.
        f"{_TLS_PROBE}; "
        "exit $rc"
    )


def python_tls_check_command(
    revoked: tuple[str, ...] | list[str] = REVOKED_CA_NAMES,
    venv_activate: str = "",
) -> str:
    """Verify the certifi bundle, which is the store pip, requests and
    ComfyUI actually use — upgrading the system store does not touch it.

    `venv_activate` is an optional path to an `activate` script, for images
    whose application runs in a virtualenv with its own certifi.
    """
    program = (
        "import ssl, sys, urllib.request\n"
        "import certifi\n"
        "bundle = certifi.where()\n"
        "print('certifi', certifi.__version__, bundle)\n"
        "data = open(bundle, encoding='utf-8', errors='replace').read()\n"
        # certifi carries a '# Label: \"...\"' comment per root. Without
        # them a name search would pass on any bundle, so say so loudly
        # rather than report a clean result we cannot stand behind.
        "if '# Label:' not in data:\n"
        "    print('FAIL: certifi bundle carries no labels — '\n"
        "          'cannot match roots by name')\n"
        "    sys.exit(1)\n"
        f"revoked = {list(revoked)!r}\n"
        "found = [n for n in revoked if n.lower() in data.lower()]\n"
        "if found:\n"
        "    print(f'FAIL: revoked CA present in certifi bundle: {found}')\n"
        "    sys.exit(1)\n"
        "print(f'certifi bundle clean ({len(revoked)} name(s) checked)')\n"
        "ctx = ssl.create_default_context(cafile=bundle)\n"
        "with urllib.request.urlopen('https://pypi.org/simple/',\n"
        "                            context=ctx, timeout=30) as r:\n"
        "    assert r.status == 200, f'pypi returned {r.status}'\n"
        "print('https fetch via certifi ok')\n"
    )
    if venv_activate:
        # The app venv ships its own certifi; its activate puts python on PATH.
        prefix = f". {shlex.quote(venv_activate)}; "
        interp = "python"
    else:
        # SSH exec PATH often drops /usr/local/bin (the base `python` symlink),
        # and some images expose only python3. Add the dir back and resolve
        # whichever interpreter exists.
        prefix = (
            "export PATH=/usr/local/bin:$PATH; "
            "PYBIN=$(command -v python || command -v python3) "
            "|| { echo 'FAIL: no python on PATH'; exit 1; }; "
        )
        interp = '"$PYBIN"'
    return f"{prefix}{interp} - <<'PY'\n{program}PY"


def uv_check_command() -> str:
    """Verify uv is the single pinned copy and can actually resolve.

    The duplicate test is the point: the NGC bases ship a pip-installed uv
    in /usr/local/bin that shadows the pinned /bin/uv and keeps showing up
    in scans. The Dockerfiles remove it, and this fails the build if a base
    image brings it back.

    /usr/local/bin is forced onto PATH: the SSH exec PATH often drops it, and
    without it the scan cannot see a uv there and `python` (the base-image
    symlink) is not found, so the pip-package guard would silently skip.
    """
    return (
        "set -e; "
        "export PATH=/usr/local/bin:$PATH; "
        "uv --version; "
        f"{_UV_PATH_SCAN}; "
        "echo \"uv on PATH:\"; printf '%s\\n' \"$FOUND\"; "
        "COUNT=$(printf '%s\\n' \"$FOUND\" | sed '/^$/d' | wc -l "
        "  | tr -d '[:space:]'); "
        "[ \"$COUNT\" -eq 1 ] "
        "  || { echo \"FAIL: expected one uv on PATH, found $COUNT\"; exit 1; }; "
        "if command -v python >/dev/null 2>&1; then "
        "  if python -m pip show uv >/dev/null 2>&1; then "
        "    echo 'FAIL: uv is also installed as a pip package'; exit 1; "
        "  fi; "
        "  echo 'no pip-installed uv'; "
        "fi; "
        "TMP=$(mktemp -d); "
        "uv venv \"$TMP/venv\" >/dev/null; "
        "uv pip install --python \"$TMP/venv/bin/python\" --quiet six; "
        "\"$TMP/venv/bin/python\" -c "
        "  \"import six; print('uv pip install ok', six.__version__)\"; "
        "rm -rf \"$TMP\""
    )


def virtualenv_check_command() -> str:
    """Create a virtualenv with every python3.X the image ships.

    The images pin one virtualenv version across four interpreters, and a
    pin that stops supporting the oldest of them fails only for whoever
    happens to use that interpreter. Enumerating what is installed is the
    whole check — a hard-coded list would pass by testing nothing after an
    interpreter is dropped.
    """
    return (
        "set -e; "
        "PYS=$(ls /usr/local/bin/python3.* /usr/bin/python3.* 2>/dev/null "
        "  | grep -E 'python3\\.[0-9]+$' || true); "
        "[ -n \"$PYS\" ] "
        "  || { echo 'FAIL: no python3.X interpreters found'; exit 1; }; "
        "TMP=$(mktemp -d); "
        "for py in $PYS; do "
        "  VER=$(\"$py\" -c 'import sys; print(\"%d.%d\" % sys.version_info[:2])'); "
        # Both /usr/bin and /usr/local/bin can expose the same interpreter;
        # key on the version so each one is exercised once. `if` rather than
        # `[ ... ] && continue` for the same reason as the uv PATH scan.
        "  if [ -d \"$TMP/v$VER\" ]; then continue; fi; "
        "  \"$py\" -m virtualenv -q \"$TMP/v$VER\"; "
        "  \"$TMP/v$VER/bin/python\" -c "
        "    \"import sys; print('virtualenv ok for $VER ->', "
        "     sys.version.split()[0])\"; "
        "done; "
        "rm -rf \"$TMP\"; "
        "echo 'virtualenv ok on every interpreter'"
    )


def autoresearch_check_command(
    time_budget: int = 5, seq_len: int = 256, eval_tokens: int = 1 << 18,
) -> str:
    """Run the real autoresearch command (train.py) end to end, but light:
    a short time budget, a short sequence length (the batch x seq activations,
    not the ~100M model, drive VRAM, so this fits a cheap GPU), and a small
    eval. All three live in the read-only prepare.py and are patched via runpy
    so train.py is untouched; torch.compile runs for real, hence the generous
    timeout the caller must allow."""
    return (
        "set -e; "
        ". /opt/autoresearch/.venv/bin/activate; "
        "cd /opt/autoresearch; "
        "python -c \""
        f"import prepare; prepare.TIME_BUDGET = {time_budget}; "
        f"prepare.MAX_SEQ_LEN = {seq_len}; prepare.EVAL_TOKENS = {eval_tokens}; "
        "import runpy; runpy.run_path('train.py', run_name='__main__')\"; "
        "echo 'autoresearch train.py ok'"
    )


def run_simple_check(
    endpoint: SshEndpoint, command: str, timeout: int = 180,
) -> tuple[bool, str]:
    """Run one opt-in hygiene check over SSH. Returns (ok, output)."""
    try:
        r = run_ssh(endpoint, command, timeout)
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {timeout}s"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    return (r.returncode == 0), _strip_cr(r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# Jupyter checks (opt-in)
# ---------------------------------------------------------------------------


def jupyter_check_command(timeout: int) -> str:
    """Shell snippet (run via SSH on the pod) that verifies Jupyter Lab is
    actually running and answers HTTP with the token we set via env.

    Why both `jupyter server list` AND a `curl`: the list catches the silent
    `python3 -m jupyter` failure mode (server never started — list is empty
    even though start.sh printed 'Jupyter Lab started'); the curl catches
    "process is alive but http endpoint is wedged" or "token mismatch".

    Polls for up to `timeout` seconds because start.sh launches Jupyter in
    background via `nohup ... &` and exits without waiting; the HTTP port
    typically becomes reachable a few seconds after the pod logs say it is.
    """
    return (
        "set -e; "
        # Wait for the HTTP port to open. Don't rely on `jupyter` CLI being
        # in PATH yet (the binary IS in PATH from the base image, but the
        # server takes a few seconds to bind). Use raw /dev/tcp instead so
        # we don't need nc / curl just to detect "listening".
        f"for i in $(seq 1 {timeout}); do "
        "  if (echo > /dev/tcp/127.0.0.1/8888) 2>/dev/null; then break; fi; "
        "  sleep 1; "
        "done; "
        # Server should appear in `jupyter server list`. If start.sh used
        # the wrong python interpreter, this is empty.
        "echo '--- jupyter server list ---'; "
        "OUT=$(jupyter server list 2>&1 || true); "
        "echo \"$OUT\"; "
        "echo \"$OUT\" | grep -qE 'http://[^ ]*:8888' "
        "  || { echo 'FAIL: no Jupyter server listening on :8888'; exit 1; }; "
        # API responds with our token. /api/status is a tiny endpoint that
        # returns 200 + JSON when the server is healthy AND auth passes.
        "echo '--- curl /api/status ---'; "
        f"curl -sS --max-time 10 -o /tmp/_jupyter_status "
        f"  -w 'http=%{{http_code}}\\n' "
        f"  \"http://127.0.0.1:8888/api/status?token={config.JUPYTER_TEST_PASSWORD}\" "
        "  || { echo 'FAIL: curl to :8888 failed'; exit 1; }; "
        "cat /tmp/_jupyter_status; echo; "
        "grep -qE '^http=200' /tmp/_jupyter_status 2>/dev/null "
        "  || grep -qE '\"started\"' /tmp/_jupyter_status "
        "  || { echo 'FAIL: /api/status did not return 200 with valid token'; "
        "       exit 1; }; "
        "echo 'jupyter check OK'"
    )


def run_jupyter_check(endpoint: SshEndpoint) -> tuple[bool, str]:
    """SSH into the pod and run the jupyter probe against 127.0.0.1:8888.

    This validates the IN-POD side: start.sh launched Jupyter with the
    right interpreter, server bound to :8888, our token works.

    Returns (ok, output). ok=False when the SSH call itself failed, OR
    when jupyter probe exited non-zero (server not running / wrong token
    / API not healthy)."""
    cmd = jupyter_check_command(config.JUPYTER_WAIT_TIMEOUT)
    # SSH command has its own grace loop (JUPYTER_WAIT_TIMEOUT) plus a 10s
    # curl; pad the outer timeout to leave room for SSH handshake.
    outer_timeout = config.JUPYTER_WAIT_TIMEOUT + 30
    try:
        r = run_ssh(endpoint, cmd, outer_timeout)
    except subprocess.TimeoutExpired:
        return False, f"jupyter check timed out after {outer_timeout}s"
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    combined = _strip_cr(r.stdout + r.stderr).strip()
    return (r.returncode == 0), combined


# ---------------------------------------------------------------------------
# Generic per-port checks (test_ports manifest field)
# ---------------------------------------------------------------------------

def port_check_command(test_port: int, wait_timeout: int) -> str:
    """Wait for localhost HTTP readiness; 4xx is a valid app response."""
    return (
        "set -e; "
        f"echo 'Probing 127.0.0.1:{test_port} (timeout {wait_timeout}s)...'; "
        "CODE=pending; "
        f"for i in $(seq 1 {wait_timeout}); do "
        f"  if (echo > /dev/tcp/127.0.0.1/{test_port}) 2>/dev/null; then "
        f"    CODE=$(curl -sS --max-time 5 -o /dev/null "
        f"      -w '%{{http_code}}' 'http://127.0.0.1:{test_port}/' "
        "      || echo 'curl_failed'); "
        "    case \"$CODE\" in "
        f"      [1234]*) echo \"port {test_port} responsive after $i"
        "s: http=$CODE\"; break ;; "
        "      *) ;; "
        "    esac; "
        "  fi; "
        "  if [ $((i % 30)) -eq 0 ]; then "
        f"    echo \"  ...still probing :{test_port} at ${{i}}s/{wait_timeout}s "
        "(last code=$CODE)\"; "
        "  fi; "
        "  sleep 1; "
        "done; "
        "case \"$CODE\" in "
        f"  [1234]*) echo 'port {test_port} OK' ;; "
        f"  pending) echo 'FAIL: nothing ever listened on 127.0.0.1:{test_port} "
        f"within {wait_timeout}s'; exit 1 ;; "
        f"  *) echo \"FAIL: port {test_port} never returned HTTP <500 "
        f"within {wait_timeout}s (last code: $CODE)\"; exit 1 ;; "
        "esac"
    )


def run_port_check(
    endpoint: SshEndpoint,
    test_port: int,
    on_line: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Run the in-pod fallback probe with live progress and a hard timeout."""
    remote_cmd = port_check_command(test_port, config.PORT_WAIT_TIMEOUT)
    ssh_cmd = _ssh_command_prefix(endpoint)
    if not endpoint.pty:
        ssh_cmd.append(remote_cmd)
    outer_timeout = config.PORT_WAIT_TIMEOUT + 60
    try:
        proc = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE if endpoint.pty else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return False, _SSH_BINARY_NOT_FOUND
    assert proc.stdout is not None
    if endpoint.pty:
        # See _pty_script: the proxy ignores a command argument.
        assert proc.stdin is not None
        # Left open until the session ends — see _run_pty.
        proc.stdin.write(_pty_script(remote_cmd))
        proc.stdin.flush()
    # On a PTY the prompt and our own typing come first; stream only what
    # the command printed, between the markers.
    in_body = not endpoint.pty
    pty_rc: Optional[int] = None

    timed_out = [False]

    def kill_on_timeout() -> None:
        timed_out[0] = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(outer_timeout, kill_on_timeout)
    watchdog.daemon = True
    watchdog.start()
    last_line = ""
    try:
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\r\n")
            if endpoint.pty:
                if line == _PTY_BEGIN:
                    in_body = True
                    continue
                m = _PTY_RC_RE.match(line) if in_body else None
                if m:
                    pty_rc, in_body = int(m.group(1)), False
                    continue
            if line and in_body:
                if on_line:
                    on_line(line)
                last_line = line
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception as exc:  # noqa: BLE001
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"port {test_port} check errored: {exc}"
    finally:
        watchdog.cancel()
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    if timed_out[0]:
        return False, (
            f"port {test_port} check wall-clock timeout after {outer_timeout}s"
        )
    if endpoint.pty:
        return pty_rc == 0, last_line
    return proc.returncode == 0, last_line


def _proxy_status_ok(code: int) -> bool:
    """A service is healthy through the public proxy only on HTTP 200."""
    return code == 200


def run_port_proxy_check(pod_id: str, test_port: int) -> tuple[bool, str]:
    """Probe a generic HTTP service through RunPod's public proxy."""
    url = f"{config.proxy_url(pod_id, test_port)}/"
    deadline = time.monotonic() + config.PORT_PROXY_TIMEOUT
    lines = [f"GET {url}"]
    last_error = ""
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "runpod-smoke-test/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                code = response.status
                body = response.read(256).decode("utf-8", errors="replace")
                lines.append(
                    f"attempt #{attempt}: HTTP {code} body={body[:160]!r}"
                )
                if _proxy_status_ok(code):
                    return True, "\n".join(lines)
                last_error = f"HTTP {code}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            lines.append(f"attempt #{attempt}: {last_error}")
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            lines.append(f"attempt #{attempt}: {last_error}")
        time.sleep(5)
    lines.append(
        f"FAIL: no HTTP 200 via proxy after {config.PORT_PROXY_TIMEOUT}s "
        f"({attempt} attempts), last error: {last_error}"
    )
    return False, "\n".join(lines)


def run_jupyter_proxy_check(pod_id: str) -> tuple[bool, str]:
    """Hit `https://<pod-id>-8888.<proxy domain>/api/status?token=admin`
    from the test machine. Verifies that:

      1. RunPod's public proxy has the pod registered for port 8888.
         If the port was exposed as `8888/tcp` instead of `8888/http`, the
         proxy never wires it up and this fails. The SSH-side check would
         still pass — that's exactly the kind of misconfiguration the
         end-user would hit when they tried to open Jupyter from the UI.
      2. Jupyter is reachable end-to-end, not just on localhost.

    Retries for up to JUPYTER_PROXY_TIMEOUT seconds because the proxy is
    eventually-consistent: a freshly-created pod may not be in its routing
    table for ~10–30s. Returns (ok, multi-line log).
    """
    url = (
        f"{config.proxy_url(pod_id, 8888)}/api/status"
        f"?token={config.JUPYTER_TEST_PASSWORD}"
    )
    # Same URL with the token stripped — used in log lines so we never
    # write the bearer token to stdout / CI logs. The real `url` (with
    # token) only ever goes to urlopen.
    redacted_url = (
        f"{config.proxy_url(pod_id, 8888)}/api/status?token=<redacted>"
    )
    deadline = time.monotonic() + config.JUPYTER_PROXY_TIMEOUT
    lines = [f"GET {redacted_url}"]
    last_err = ""
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "runpod-smoke-test/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
                body = resp.read(2048).decode("utf-8", errors="replace")
                lines.append(
                    f"attempt #{attempt}: HTTP {code} body={body[:200]}"
                )
                if code == 200:
                    return True, "\n".join(lines)
                last_err = f"HTTP {code}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
            lines.append(f"attempt #{attempt}: {last_err}")
        except OSError as exc:
            # urllib.error.URLError and the builtin TimeoutError both derive
            # from OSError, so this single clause covers connection refused,
            # DNS failures, socket timeouts, and 'No route to host' alike.
            last_err = f"{type(exc).__name__}: {exc}"
            lines.append(f"attempt #{attempt}: {last_err}")
        time.sleep(5)

    lines.append(
        f"FAIL: proxy unreachable after {config.JUPYTER_PROXY_TIMEOUT}s "
        f"({attempt} attempts), last error: {last_err}"
    )
    return False, "\n".join(lines)


def run_jupyter_static_check(pod_id: str) -> tuple[bool, str]:
    """Hit a static asset through the public proxy.

    `/api/status` is served by a plain handler and stays 200 even when every
    StaticFileHandler route 500s — which is what tornado 6.5.9 did to
    jupyter_server (tornadoweb/tornado#3724) and what makes the Lab UI render
    as a blank page. Only a static fetch covers that. Returns (ok, log).
    """
    url = f"{config.proxy_url(pod_id, 8888)}/static/favicons/favicon.ico"
    lines = [f"GET {url}"]
    err = ""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "runpod-smoke-test/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ctype = resp.headers.get("Content-Type", "")
            lines.append(f"HTTP {resp.status} content-type={ctype}")
            # A redirect to the login page would also be a 200, so reject HTML.
            if resp.status == 200 and not ctype.startswith("text/html"):
                return True, "\n".join(lines)
            err = f"HTTP {resp.status} content-type={ctype}"
    except urllib.error.HTTPError as e:
        err = f"HTTP {e.code} {e.reason}"
    except OSError as exc:
        err = f"{type(exc).__name__}: {exc}"
    lines.append(f"FAIL: static asset not served ({err}) -- Lab UI renders blank")
    return False, "\n".join(lines)


# ---------------------------------------------------------------------------
# Container logs via REST API (v2) + error scan
# ---------------------------------------------------------------------------

# Last log-API error per pod, so a repeatedly-slow stream logs once instead
# of once per poll. Keyed by pod, so a different pod still gets its own line.
_last_log_api_error: dict[str, str] = {}


def fetch_pod_logs_api(
    pod_id: str,
    tail: int = 0,
    source: str = "container",
    deadline_sec: int = 15,
) -> Optional[list[str]]:
    """Fetch the SSE backfill from `GET /v2/pods/{id}/logs`.

    The endpoint stays open for live logs. Stop after its historical
    backfill is drained (socket idle) or the deadline expires.
    """
    api_key = api.load_api_key()
    if not api_key:
        return None
    tail = tail or config.LOG_API_TAIL
    req = urllib.request.Request(
        f"{config.REST_URL}/pods/{pod_id}/logs?source={source}&tail={tail}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
            "User-Agent": "test-images.py/1.0 (+runpod-smoketest)",
        },
    )
    lines: list[str] = []
    deadline = time.monotonic() + deadline_sec
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            while time.monotonic() < deadline:
                try:
                    raw = resp.readline()
                except OSError:
                    break
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                try:
                    payload = json.loads(text[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                line = payload.get("line")
                if line is not None:
                    lines.append(line.rstrip())
    except (urllib.error.HTTPError, OSError) as exc:
        # Deduped per pod: the readiness poll asks once per interval, and a
        # pod whose log stream is slow produced ~20 identical lines per pod
        # in one ROCm run, burying everything else.
        message = f"log API fetch failed: {exc}"
        if _last_log_api_error.get(pod_id) != message:
            _last_log_api_error[pod_id] = message
            log(f"  ({message})", indent=2)
        return None
    _last_log_api_error.pop(pod_id, None)
    return lines


# The container announced that its SSH server is up. `sshd` is started by
# the entrypoint, so this is the container saying the thing we are waiting
# for already happened — anything still unreachable after it is RunPod's
# network path, not the image.
_SSHD_UP_RE = re.compile(
    # Debian/Ubuntu service script, used by container-template/start.sh
    r"Starting OpenBSD Secure Shell server sshd"
    # sshd -D in the foreground
    r"|Server listening on .* port 22\b"
    # container-template/start.sh's own last line: SSH setup is part of it
    r"|Start script\(s\) finished, Pod is ready to use",
    re.IGNORECASE,
)


class ContainerProgress(NamedTuple):
    """How far the container got, read from its own log stream.

    `status` cannot answer either question: RunPod reports `RUNNING` from the
    moment the pod is scheduled, while the image may still be downloading for
    another ten minutes — a 50GB ROCm base routinely is.

    `started` is False while the image is still being pulled, because the
    container does not exist yet and its log stream is empty. `sshd_up` means
    the entrypoint got as far as bringing SSH up, which is what separates
    "the image never opened a door" from "RunPod never built a road to it".
    """

    started: bool
    sshd_up: bool


def container_progress(
    pod_id: str, deadline_sec: int = 8
) -> Optional[ContainerProgress]:
    """Read the container's progress, or None if the log API was unreachable.

    None is distinct from `ContainerProgress(False, False)`: the first means
    "could not look", the second "looked, nothing there yet".
    """
    lines = fetch_pod_logs_api(
        pod_id, source="container", deadline_sec=deadline_sec
    )
    if lines is None:
        return None
    return ContainerProgress(
        started=bool(lines),
        sshd_up=any(_SSHD_UP_RE.search(line) for line in lines),
    )


# The host-side system log narrates the pull and hand-off in plain text, so
# the stage a pod reached can be read directly instead of inferred:
#
#   <layer> Extracting [====>]  1.2MB/13.3MB
#   <layer> Pull complete
#   Status: Downloaded newer image for runpod/comfyui:1.4.6-cuda12.8
#   create container runpod/comfyui:1.4.6-cuda12.8
#   start container for runpod/comfyui:1.4.6-cuda12.8: begin
#
# RunPod re-checks the image after creating the container, so these markers
# are not strictly ordered — the furthest stage seen is what counts.
_SYS_PULLING_RE = re.compile(
    r"\bExtracting\b|\bDownloading\b|\bPull complete\b|\bPulling from\b",
    re.IGNORECASE,
)
_SYS_PULL_DONE_RE = re.compile(
    r"\bStatus:\s*(?:Downloaded newer image|Image is up to date)\s+for\b",
    re.IGNORECASE,
)
_SYS_CONTAINER_START_RE = re.compile(
    r"\b(?:create|start) container\b", re.IGNORECASE
)


class PodStage(NamedTuple):
    """How far RunPod got with the pod, per its own system log."""

    pulling: bool
    pull_done: bool
    container_started: bool

    @property
    def label(self) -> str:
        if self.container_started:
            return "container started"
        if self.pull_done:
            return "image pulled, container not started yet"
        if self.pulling:
            return "still pulling the image"
        return "no pull or start activity logged yet"


def pod_stage(pod_id: str, deadline_sec: int = 8) -> Optional[PodStage]:
    """Read the pod's stage from the system log, or None if unreachable.

    Preferred over guessing from the container's log, which only says
    "something ran"; this says whether RunPod has even finished downloading.
    `status` says `RUNNING` throughout and cannot distinguish any of it.
    """
    lines = fetch_pod_logs_api(
        pod_id, source="system", deadline_sec=deadline_sec
    )
    if lines is None:
        return None
    return PodStage(
        pulling=any(_SYS_PULLING_RE.search(line) for line in lines),
        pull_done=any(_SYS_PULL_DONE_RE.search(line) for line in lines),
        container_started=any(
            _SYS_CONTAINER_START_RE.search(line) for line in lines
        ),
    )


def filter_sys_errors(lines: list[str], max_lines: int = 20) -> list[str]:
    """Keep the lines matching `SYS_LOG_ERROR_PATTERN`, for display.

    Deliberately narrow — it exists to shorten a long system log down to
    something worth printing. It is NOT a startup-failure detector: the
    pattern only matches error/fail/crash wording, so lines like
    `exec: "/start.sh": no such file or directory` fall through it. Anything
    classifying a failure must read the unfiltered stream.
    """
    pattern = re.compile(config.SYS_LOG_ERROR_PATTERN, re.IGNORECASE)
    return [line for line in lines if pattern.search(line)][:max_lines]


def system_log_errors(pod_id: str, max_lines: int = 20) -> Optional[list[str]]:
    """Return error-marker lines from the host-side REST system-log stream."""
    lines = fetch_pod_logs_api(pod_id, source="system")
    if lines is None:
        return None
    return filter_sys_errors(lines, max_lines)


# `nvidia-container-cli` aborts the prestart hook when the image's
# NVIDIA_REQUIRE_CUDA floor is above the host driver.
_HOST_INCOMPATIBLE_RE = re.compile(
    r"nvidia-container-cli:[^\n]*requirement error"
    r"|unsatisfied condition:\s*cuda",
    re.IGNORECASE,
)
_CUDA_CONDITION_RE = re.compile(
    r"unsatisfied condition:\s*(cuda\s*[<>=!]+\s*[\d.]+)", re.IGNORECASE
)

# The container could not be started, or its entrypoint died on the spot.
# Every one of these is deterministic: the same image fails the same way on
# any host, so a pod that times out with one of these in its log is a broken
# image and must not be reported as a retryable capacity problem.
_STARTUP_FAILURE_RE = re.compile(
    # runc/containerd refusing the container outright
    r"oci runtime (?:create|exec) failed"
    r"|standard_init_linux\.go:\d+: exec user process caused"
    # a wrong-architecture or non-executable entrypoint
    r"|exec format error"
    r"|exec:? .*(?:not found|no such file or directory)"
    r"|permission denied.*(?:start\.sh|entrypoint)"
    # the entrypoint itself giving up
    r"|/start\.sh: line \d+:[^\n]*(?:command not found|cannot execute)"
    # the kernel killing it before sshd could come up
    r"|out of memory: killed process|oom-kill",
    re.IGNORECASE,
)


def container_startup_failure(log_lines: Optional[list[str]]) -> str:
    """Summarize a deterministic container-start failure, or '' if none.

    Read before a readiness timeout is blamed on the host: an image whose
    entrypoint cannot execute looks exactly like a slow host from the
    outside — no SSH, no RUNNING, no terminal status — but no other GPU will
    fix it.
    """
    for line in log_lines or []:
        if _STARTUP_FAILURE_RE.search(line):
            return line.strip()[:200]
    return ""


def host_incompatibility(sys_errors: Optional[list[str]]) -> str:
    """Summarize a container-init rejection, or '' if there wasn't one.

    Unlike a dead host, this verdict is deterministic: the same image on the
    same pinned CUDA is rejected by every host, so the caller must not retry
    other instance types.
    """
    for line in sys_errors or []:
        if not _HOST_INCOMPATIBLE_RE.search(line):
            continue
        match = _CUDA_CONDITION_RE.search(line)
        return match.group(1) if match else line.strip()[:200]
    return ""


_LOG_SCAN_ATTEMPTS = 3
_LOG_SCAN_RETRY_SLEEP_SEC = 10


def scan_pod_logs_for_errors(pod_id: str) -> tuple[bool, str]:
    """Scan container stdout for configured errors.

    Empty API responses are retried and then fail as unverified: every
    supported image emits boot logs, so zero lines cannot prove a clean boot.
    """
    if not api.load_api_key():
        return True, "(no API key — log scan skipped)"
    failures: list[str] = []
    for attempt in range(1, _LOG_SCAN_ATTEMPTS + 1):
        lines = fetch_pod_logs_api(pod_id)
        if lines:
            break
        failures.append(
            f"attempt #{attempt}: "
            + ("fetch failed" if lines is None else "0 log lines")
        )
        if attempt < _LOG_SCAN_ATTEMPTS:
            time.sleep(_LOG_SCAN_RETRY_SLEEP_SEC)
    else:
        return False, (
            "log scan UNVERIFIED — the log API returned no container logs "
            f"after {_LOG_SCAN_ATTEMPTS} attempts ({'; '.join(failures)})"
        )

    pattern = re.compile(config.LOG_ERROR_PATTERN, re.IGNORECASE)
    matches = [line for line in lines if pattern.search(line)]
    if not matches:
        return True, f"scanned {len(lines)} log lines — no error markers"
    report = [
        f"scanned {len(lines)} log lines — "
        f"{len(matches)} matched /{config.LOG_ERROR_PATTERN}/i:"
    ]
    report.extend(f"  {line}" for line in matches[:40])
    if len(matches) > 40:
        report.append(f"  ... (+{len(matches) - 40} more)")
    return False, "\n".join(report)


# ---------------------------------------------------------------------------
# Diagnostic log fetch
# ---------------------------------------------------------------------------


def _gpu_smi_block(image: str) -> str:
    """Pick the right vendor SMI for the diagnostic dump.

    This mirrors `cuda_check_command`: ROCm image refs get `rocm-smi`,
    CUDA/GPU image refs get `nvidia-smi`, and CPU images skip the SMI
    section entirely.
    """
    if _image_expects_rocm(image):
        return (
            "echo '=== rocm-smi ==='; "
            "if command -v rocm-smi >/dev/null 2>&1; then "
            "  rocm-smi 2>&1 | head -n 25; "
            "else "
            "  echo '(rocm-smi not in PATH)'; "
            "fi; "
        )
    if _image_expects_gpu(image):
        return (
            "echo '=== nvidia-smi ==='; "
            "if command -v nvidia-smi >/dev/null 2>&1; then "
            "  nvidia-smi 2>&1 | head -n 15; "
            "else "
            "  echo '(nvidia-smi not in PATH)'; "
            "fi; "
        )
    return ""


def fetch_logs_via_ssh(
    endpoint: SshEndpoint, image: str,
) -> Optional[str]:
    """Fetch the GPU SMI snapshot, the remaining SSH-only diagnostic."""
    if not config.SSH_LOG_FETCH:
        return None
    smi_block = _gpu_smi_block(image)
    if not smi_block:
        return None
    remote_cmd = "set +e; " + smi_block
    try:
        r = run_ssh(endpoint, remote_cmd, 45)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout
    return f"__SSH_FAILED__\nreturncode={r.returncode}\nstderr: {r.stderr.strip()[:400]}"


class PodDiagnostics(NamedTuple):
    """What the log dump found, for a caller that has to classify a failure.

    Every stream is returned so the verdict is reached without fetching any
    of them a second time.

    `sys_lines` is the platform's own log, unfiltered — a container that
    could not be started is reported here and nowhere else, since a
    container that never ran has no stdout of its own. `sys_errors` is the
    same stream narrowed for display; do not classify from it, because its
    pattern only matches error/fail/crash wording and misses markers like
    `exec: "/start.sh": no such file or directory`.

    `container_lines` is the image's own stdout, where an entrypoint that
    started and then died reports itself.
    """

    sys_errors: list[str]
    container_lines: list[str]
    sys_lines: list[str] = []


def dump_pod_logs(pod_id: str, image: str) -> PodDiagnostics:
    """Print metadata, API container logs, system errors, and GPU SMI."""
    sys_errors: list[str] = []
    api_lines: list[str] = []
    sys_lines: list[str] = []
    status, data = api.request("GET", f"/pods/{pod_id}", timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        api.log_error("(could not fetch pod state)", status, data, indent=2)
        return PodDiagnostics(sys_errors, api_lines, sys_lines)
    ssh = data.get("ssh") or {}
    direct = ssh.get("direct") or {}
    proxy = ssh.get("proxy") or {}
    endpoint = SshEndpoint("", 0)
    if direct.get("host") and direct.get("port"):
        endpoint = SshEndpoint(str(direct["host"]), int(direct["port"]))
    # Fall back to the proxy so the SMI snapshot still gets fetched on pods
    # that never received a direct TCP port.
    elif proxy.get("host") and proxy.get("username"):
        endpoint = SshEndpoint(
            str(proxy["host"]), int(proxy.get("port") or 22),
            str(proxy["username"]), str(proxy.get("command") or ""), pty=True,
        )

    log(f"--- pod metadata for {pod_id} ---", indent=2)
    for key, val in [
        ("status",           data.get("status")),
        ("cudaVersion",      data.get("cudaVersion")),
        ("dataCenterId",     data.get("dataCenterId")),
        ("cost",             data.get("cost")),
        ("ssh.direct",       f"{direct['host']}:{direct['port']}"
                             if direct.get("host") and direct.get("port")
                             else None),
        ("ssh.proxy",        proxy.get("host") or None),
        ("image",            data.get("image")),
        ("startedAt",        data.get("startedAt")),
    ]:
        log(f"  {key:20s} = {val!r}", indent=2)

    api_lines = fetch_pod_logs_api(pod_id) or []
    if api_lines:
        log(f"--- container logs via API ({len(api_lines)} lines) ---", indent=2)
        for line in api_lines:
            log(f"  {line}", indent=2)

    # Fetched once and kept in both shapes: the unfiltered stream is what
    # the failure classifier needs, the filtered one is what is worth printing.
    sys_lines = fetch_pod_logs_api(pod_id, source="system") or []
    sys_errors = filter_sys_errors(sys_lines)
    if sys_errors:
        log(
            f"--- system-log error markers via API ({len(sys_errors)}) ---",
            indent=2,
        )
        for line in sys_errors:
            log(f"  {line}", indent=2)

    if not endpoint:
        log("  (no SSH endpoint yet — skipping GPU SMI fetch)", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return PodDiagnostics(sys_errors, api_lines, sys_lines)

    logs = fetch_logs_via_ssh(endpoint, image)
    if logs is None:
        return PodDiagnostics(sys_errors, api_lines, sys_lines)
    log(f"--- GPU SMI via SSH ({endpoint.label}) ---", indent=2)
    if logs.startswith("__SSH_FAILED__"):
        log("  SSH could not reach the pod:", indent=2)
        for line in logs.splitlines()[1:]:
            log(f"    {line}", indent=2)
        log(f"  inspect via UI: https://www.runpod.io/console/pods/{pod_id}", indent=2)
        return PodDiagnostics(sys_errors, api_lines, sys_lines)
    for line in logs.splitlines():
        log(f"  {line}", indent=2)
    return PodDiagnostics(sys_errors, api_lines, sys_lines)
