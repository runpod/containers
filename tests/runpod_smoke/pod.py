"""Pod creation, lifecycle tracking, signal-safe cleanup, registry auth.

Owns the `ACTIVE_POD_IDS` set + lock — the source of truth for "what's
still alive on RunPod" across all workers. atexit + SIGINT/SIGTERM
handlers are installed at import time so anything we leak on crash
gets terminated.
"""

from __future__ import annotations

import atexit
import json
import re
import signal
import sys
import threading
import time
from typing import Optional

from . import config
from .checks import ssh_probe
from .instances import detect_cuda_version
from .log import log
from .runpodctl import runpodctl, runpodctl_json


# ---------------------------------------------------------------------------
# Error-classification regexes
# ---------------------------------------------------------------------------

UNAVAILABLE_RE = re.compile(
    # RunPod-specific phrasings observed in pod-create errors:
    r"no\s+longer\s+any\s+instances\s+available"
    r"|please\s+refresh\s+and\s+try\s+again"
    # "This machine does not have the resources to deploy your pod. Please
    # try a different machine" — RunPod returns this when a candidate host
    # was picked but couldn't actually fit the pod (vRAM, disk, CPU). Same
    # remediation as "no capacity": move on to the next instance type.
    r"|does\s+not\s+have\s+the\s+resources"
    r"|try\s+a\s+different\s+machine"
    # Generic capacity-shortage phrasings:
    r"|no\s+(?:machines|capacity|hosts|gpus|instances)\s+available"
    r"|insufficient\s+capacity"
    r"|unavailable"
    r"|out\s+of\s+stock"
    r"|sold\s+out",
    re.IGNORECASE,
)

# Generic "RunPod orchestrator hiccupped" errors that we should retry rather
# than treat as a real failure. These appear when several workers race for
# the same scarce GPU at the same instant, or the API is just transiently
# flaky.
TRANSIENT_RE = re.compile(
    r"something\s+went\s+wrong"
    r"|please\s+try\s+again\s+later"
    r"|contact\s+support"
    r"|internal\s+server\s+error"
    r"|timeout|timed\s+out"
    r"|502|503|504"
    r"|connection\s+(?:reset|refused)",
    re.IGNORECASE,
)

RUNTIME_ERROR_RE = re.compile(
    r"toomanyrequests"
    r"|rate\s+limit"
    r"|failed\s+to\s+pull\s+image"
    r"|error\s+creating\s+container"
    r"|manifest\s+(?:unknown|not\s+found)"
    r"|access\s+denied"
    r"|no\s+such\s+image",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Active-pod tracking + signal-safe cleanup
# ---------------------------------------------------------------------------

# Set of pod IDs that are currently alive across all workers. Used by
# signal handlers / atexit to ensure NOTHING leaks when the script dies.
# Guarded by a lock so parallel workers can register/deregister safely.
ACTIVE_POD_IDS: set[str] = set()
_active_pods_lock = threading.Lock()


def register_pod(pod_id: str) -> None:
    with _active_pods_lock:
        ACTIVE_POD_IDS.add(pod_id)


def unregister_pod(pod_id: str) -> None:
    with _active_pods_lock:
        ACTIVE_POD_IDS.discard(pod_id)


def cleanup_pod(pod_id: str) -> None:
    """Delete a single pod and unregister it from the tracking set."""
    if not pod_id:
        return
    log(f"Cleaning up pod {pod_id}...")
    runpodctl("pod", "delete", pod_id, timeout=30)
    unregister_pod(pod_id)


def cleanup_all() -> None:
    """Delete every pod still tracked as active. Used at exit / on signal."""
    with _active_pods_lock:
        leftover = list(ACTIVE_POD_IDS)
    if not leftover:
        return
    log(f"Cleaning up {len(leftover)} leftover pod(s)...")
    for pid in leftover:
        try:
            runpodctl("pod", "delete", pid, timeout=30)
        except Exception as exc:  # noqa: BLE001
            log(f"  failed to delete {pid}: {exc}")
        unregister_pod(pid)


atexit.register(cleanup_all)


def _signal_handler(signum: int, _frame) -> None:
    log(f"Caught signal {signum}, cleaning up...")
    cleanup_all()
    sys.exit(130)


for _sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(_sig, _signal_handler)


# ---------------------------------------------------------------------------
# Registry auth discovery
# ---------------------------------------------------------------------------


def discover_registry_auth(prefer_name: str = "") -> Optional[str]:
    """Find a registry auth id from `runpodctl registry list`."""
    data = runpodctl_json("registry", "list", timeout=30)
    if not isinstance(data, list) or not data:
        return None
    if prefer_name:
        for item in data:
            if (item.get("name") or "").lower() == prefer_name.lower():
                return item.get("id") or item.get("registryAuthId")
    first = data[0]
    return first.get("id") or first.get("registryAuthId")


# ---------------------------------------------------------------------------
# Pod create / state
# ---------------------------------------------------------------------------


def _extract_error(raw: str) -> str:
    """Pull a concise error string out of runpodctl's noisy create-failure
    output (which usually dumps the JSON error followed by a full `--help`
    listing)."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{") and '"error"' in line:
            try:
                return json.loads(line).get("error", line)
            except json.JSONDecodeError:
                return line
        if line and line.split()[0] in {"Usage:", "Flags:", "Aliases:",
                                         "Examples:", "Global"}:
            break
        if line:
            return line
    return raw[:200]


def create_pod(
    image: str,
    gpu_id: str,
    name: str,
    *,
    compute_type: str = "GPU",
    group: Optional[str] = None,
    test_jupyter: bool = False,
) -> tuple[Optional[str], str]:
    """Create a pod via `runpodctl pod create`. Returns (pod_id, raw_output).

    compute_type='GPU' uses --gpu-id to target a specific GPU type (caller
    must pass a non-empty gpu_id).
    compute_type='CPU' creates a CPU pod; runpodctl 2.3.0 does NOT let us
    pick a specific CPU flavor (--gpu-id is rejected for CPU), so RunPod
    chooses one for us. gpu_id is ignored in CPU mode.

    `group` is used to look up `min_cuda_version` from the manifest when
    the image tag doesn't encode a CUDA version (e.g. NGC
    `nvidia-pytorch:25.11`).

    `test_jupyter=True` expands the pod config so JupyterLab can be tested:
        - `--ports` gains `8888/http`
        - `--env` sets `JUPYTER_PASSWORD` (the value start.sh checks before
          starting Jupyter)
    """
    disk_gb = config.CPU_DISK_GB if compute_type == "CPU" else config.DISK_GB
    ports = ["22/tcp"]
    if test_jupyter:
        ports.append("8888/http")
    args = [
        "pod", "create",
        "--image", image,
        "--cloud-type", config.CLOUD_TYPE,
        "--container-disk-in-gb", str(disk_gb),
        "--ports", ",".join(ports),
        "--name", name,
        "--terminate-after", config.AUTO_TERMINATE,
        "-o", "json",
    ]
    if test_jupyter:
        # runpodctl wants --env as a single JSON-object string.
        env_obj = {"JUPYTER_PASSWORD": config.JUPYTER_TEST_PASSWORD}
        args.extend(["--env", json.dumps(env_obj)])
    if compute_type == "CPU":
        args.extend(["--compute-type", "CPU"])
        # CPU images have no CUDA, no GPU — `--min-cuda-version` would be
        # nonsensical and `--gpu-id` is rejected by runpodctl for CPU pods.
    else:
        args.extend(["--gpu-id", gpu_id, "--gpu-count", "1"])
        # Constrain scheduling to hosts whose driver supports this image's
        # CUDA. Without this, RunPod may land a cu13.0 image on an
        # older-driver host and the container fails at startup with
        # `nvidia-container-cli: cuda>=13.0`. Image tag wins; the manifest
        # `min_cuda_version` is only consulted for opaque tags (NGC etc.).
        cuda_version = (
            detect_cuda_version(image)
            or (config.GROUP_MIN_CUDA.get(group) if group else None)
        )
        if cuda_version:
            args.extend(["--min-cuda-version", cuda_version])
    if config.REGISTRY_AUTH_ID:
        args.extend(["--registry-auth-id", config.REGISTRY_AUTH_ID])
    proc = runpodctl(*args, timeout=120)
    raw = (proc.stderr + proc.stdout).strip()
    if proc.returncode != 0:
        return None, _extract_error(raw)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, _extract_error(raw)
    pod_id = data.get("id") or (data.get("pod") or {}).get("id")
    return pod_id, raw


def pod_state(pod_id: str) -> dict:
    """Return the relevant subset of pod state for decision-making.

    When the pod is created with `--ports 22/tcp` (which we do), `pod get`
    populates a useful `ssh` block with `ip`, `port`, and
    `ssh_key.in_account` once the pod is scheduled. We use these as the
    real readiness signal.
    """
    data = runpodctl_json("pod", "get", pod_id, timeout=30)
    if not isinstance(data, dict):
        return {}
    ssh = data.get("ssh") or {}
    return {
        "desired": data.get("desiredStatus"),
        "uptime": data.get("uptimeSeconds") or 0,
        "ssh_ip": ssh.get("ip") or "",
        "ssh_port": ssh.get("port") or 0,
        "ssh_error": ssh.get("error") or "",
        "ssh_key_in_account": (ssh.get("ssh_key") or {}).get("in_account"),
        "last_status_change": data.get("lastStatusChange"),
        "raw": data,
    }


def pod_status(pod_id: str) -> Optional[str]:
    """Returns `desiredStatus` — note this is always RUNNING after creation
    so it can ONLY be used to detect terminal states (EXITED/FAILED/DEAD)."""
    return pod_state(pod_id).get("desired")


# Top-level fields on `pod get` that may carry a runtime error message
# directly. Checked verbatim with `isinstance(value, str)`.
_DIRECT_ERROR_FIELDS = ("lastError", "errorMessage", "statusMessage",
                        "lastStatusChange")

# Same as above but expected on the nested `runtime` dict that RunPod
# returns alongside top-level fields.
_RUNTIME_ERROR_FIELDS = ("lastError", "errorMessage", "statusMessage")

# Fields whose value is a list of event objects (or strings); each item's
# `message` is harvested. `events` is the standard one; the other two
# show up on older `pod get` responses.
_EVENT_LIST_FIELDS = ("events", "statusEvents", "containerEvents")

# Fields whose value is a single block of log lines that may contain
# pull-time errors not surfaced anywhere else.
_LOG_BLOCK_FIELDS = ("containerLogs", "logs")


def _collect_string_field(target: list[str], src: dict, key: str) -> None:
    val = src.get(key)
    if isinstance(val, str) and val:
        target.append(val)


def _collect_event_messages(target: list[str], events: object) -> None:
    if not isinstance(events, list):
        return
    for ev in events:
        msg = ev.get("message") if isinstance(ev, dict) else str(ev)
        if isinstance(msg, str) and msg:
            target.append(msg)


def _gather_runtime_error_candidates(data: dict) -> list[str]:
    """Walk every plausible place RunPod stuffs a runtime/pull error,
    return a flat list of candidate lines. Doesn't filter — that's
    `pod_runtime_error`'s job."""
    runtime = data.get("runtime") or {}
    candidates: list[str] = []
    for key in _DIRECT_ERROR_FIELDS:
        _collect_string_field(candidates, data, key)
    for key in _RUNTIME_ERROR_FIELDS:
        _collect_string_field(candidates, runtime, key)
    for key in _EVENT_LIST_FIELDS:
        _collect_event_messages(candidates, data.get(key) or runtime.get(key))
    for key in _LOG_BLOCK_FIELDS:
        val = data.get(key) or runtime.get(key)
        if isinstance(val, str):
            candidates.extend(val.splitlines())
    return candidates


def pod_runtime_error(pod_id: str) -> Optional[str]:
    """Inspect pod-get response for container-runtime errors (pull failures,
    bad images, etc.) that appear *before* the pod ever reaches RUNNING.
    Returns a short error string or None."""
    data = runpodctl_json("pod", "get", pod_id, timeout=30)
    if not isinstance(data, dict):
        return None
    for line in _gather_runtime_error_candidates(data):
        if RUNTIME_ERROR_RE.search(line):
            return line.strip()[:300]
    return None


# ---------------------------------------------------------------------------
# Wait for the pod to become reachable
# ---------------------------------------------------------------------------


# Pod-lifecycle states that mean "we will never become RUNNING — stop polling".
_TERMINAL_DESIRED = {"EXITED", "FAILED", "DEAD", "TERMINATED"}


def _print_stall_hint(pod_id: str, elapsed: int) -> None:
    """One-time hint for pods that sit with no SSH endpoint for too long.

    RunPod doesn't surface pull progress via API/CLI, so this points the
    user at the UI plus the single most common root cause — Docker Hub
    rate-limiting an anonymous pull.
    """
    log(
        f"pod still has no SSH endpoint after {elapsed}s. "
        "Most common cause is a slow or throttled image pull. "
        "Check the UI for pull progress: "
        f"https://www.runpod.io/console/pods/{pod_id}",
        indent=2,
    )
    log(
        "If you see 'toomanyrequests' in the UI logs, you've hit the "
        "Docker Hub pull rate limit — wait 6h, log in to a paid Docker "
        "Hub account, or reduce MAX_PARALLEL.",
        indent=2,
    )


def _probe_ssh_endpoint(
    host: str,
    port: int,
    desired: object,
    elapsed: int,
    ssh_attempts: int,
    last_summary: Optional[tuple],
) -> tuple[Optional[tuple[str, str]], tuple]:
    """One SSH probe against an assigned endpoint. Returns:
        (outcome | None, summary_for_dedup)

    `outcome` is `("RUNNING", detail)` when the probe succeeds; otherwise
    None — caller keeps polling. `summary_for_dedup` is the value the
    caller compares against `last_summary` to dedup the log line.
    """
    ok, err = ssh_probe(host, port, timeout=8)
    summary = (desired, host, port, ok)
    if summary != last_summary:
        log(
            f"t+{elapsed}s endpoint=root@{host}:{port} "
            f"ssh_probe={'OK' if ok else 'FAIL'} (#{ssh_attempts})"
            + (f" — {err}" if not ok and err else ""),
            indent=2,
        )
    if ok:
        return (
            "RUNNING",
            f"ssh probe succeeded after {elapsed}s "
            f"({ssh_attempts} attempts, endpoint root@{host}:{port})",
        ), summary
    return None, summary


def wait_for_running(pod_id: str) -> tuple[str, str]:
    """Returns (outcome, detail). Outcome is one of:
        'RUNNING'   SSH probe to root@<ssh.ip>:<ssh.port> succeeded — the
                    container's sshd is up, which means the container has
                    fully booted and we can trust it as healthy.
        'TERMINAL'  desiredStatus flipped to EXITED/FAILED/DEAD/TERMINATED.
        'TIMEOUT'   SSH never reachable within CREATE_TIMEOUT — pod stuck
                    initializing (capacity issue or image broken).

    SSH probing is the real health-check now. We poll `pod get` to discover
    ssh.ip / ssh.port (assigned by RunPod once a machine is allocated), then
    try `ssh root@ip -p port 'echo ready'` until it succeeds. This works
    because:
      * `--ports 22/tcp` in pod create makes RunPod NAT a public port to the
        container's 22, so the container's sshd is reachable from anywhere.
      * The PUBLIC_KEY env we inject lands in /root/.ssh/authorized_keys.
      * A successful SSH means the container booted + sshd started — the
        canonical signal of readiness, much stronger than `desiredStatus`
        (always RUNNING) or `uptimeSeconds` (stale in this CLI version).
    """
    start = time.time()
    deadline = start + config.CREATE_TIMEOUT
    last_summary: Optional[tuple] = None
    ssh_attempts = 0
    stall_hinted = False  # one-time hint when pod has no ssh endpoint for a while

    while time.time() < deadline:
        st = pod_state(pod_id)
        if not st:
            time.sleep(config.POLL_INTERVAL)
            continue

        desired = st.get("desired")
        host = st.get("ssh_ip") or ""
        port = st.get("ssh_port") or 0
        elapsed = int(time.time() - start)

        if desired in _TERMINAL_DESIRED:
            return "TERMINAL", f"pod entered {desired} after {elapsed}s"

        if host and port:
            ssh_attempts += 1
            outcome, last_summary = _probe_ssh_endpoint(
                host, int(port), desired, elapsed, ssh_attempts, last_summary,
            )
            if outcome is not None:
                return outcome
        else:
            summary = (desired, host, port, False)
            if summary != last_summary:
                log(
                    f"t+{elapsed}s desired={desired!r} "
                    f"uptime={st.get('uptime') or 0}s "
                    "ssh endpoint not assigned yet",
                    indent=2,
                )
                last_summary = summary
            if elapsed >= config.STALL_HINT_AFTER and not stall_hinted:
                _print_stall_hint(pod_id, elapsed)
                stall_hinted = True

        time.sleep(config.POLL_INTERVAL)

    return "TIMEOUT", (
        f"SSH endpoint never became reachable in {config.CREATE_TIMEOUT}s "
        f"({ssh_attempts} probes) — pod stuck initializing. Likely causes: "
        "(1) slow/throttled image pull (check UI for pull progress), "
        "(2) Docker Hub rate limit if many parallel pulls of the same image, "
        "(3) host scheduling delay on a saturated DC"
    )
