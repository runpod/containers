"""Pod creation, lifecycle tracking, signal-safe cleanup, registry auth.

Everything here talks to REST API v2 (see api.py) — no runpodctl.

Owns the `ACTIVE_POD_IDS` set + lock — the source of truth for "what's
still alive on RunPod" across all workers. atexit + SIGINT/SIGTERM
handlers are installed at import time so anything we leak on crash
gets terminated.
"""

from __future__ import annotations

import atexit
import signal
import sys
import threading
import time
from typing import Optional

from . import api, config
from .checks import ssh_probe, system_log_errors
from .instances import detect_cuda_version, pick_cpu_flavor
from .log import log


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


def _terminate_pod(pod_id: str) -> tuple[bool, str]:
    """DELETE the pod. 404 counts as success — it's already gone."""
    status, data = api.request_with_retries(
        "DELETE", f"/pods/{pod_id}", timeout=30
    )
    if 200 <= status < 300 or status == 404:
        return True, ""
    return False, api.error_detail(status, data)


def cleanup_pod(pod_id: str) -> None:
    """Delete a single pod and unregister it from the tracking set."""
    if not pod_id:
        return
    log(f"Cleaning up pod {pod_id}...")
    ok, detail = _terminate_pod(pod_id)
    if not ok:
        # Loud, because a pod we failed to delete keeps billing until
        # reap-pods.yml catches it.
        log(f"  WARNING: could not delete {pod_id}: {detail}")
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
            ok, detail = _terminate_pod(pid)
            if not ok:
                log(f"  WARNING: could not delete {pid}: {detail}")
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
    """Find a registry credential id from `GET /v2/registries`."""
    status, data = api.request_with_retries("GET", "/registries", timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        return None
    registries = data.get("registries")
    if not isinstance(registries, list) or not registries:
        return None
    if prefer_name:
        for item in registries:
            if (item.get("name") or "").lower() == prefer_name.lower():
                return item.get("id")
    return registries[0].get("id")


# ---------------------------------------------------------------------------
# Pod create / state
# ---------------------------------------------------------------------------


def _resolve_min_cuda(image: str, group: Optional[str]) -> Optional[str]:
    """Pick the CUDA floor and log which source won.

    An explicit manifest value wins; the image tag is the fallback. Without
    a floor a cu130 image can land on a 12.x driver and die with
    `nvidia-container-cli: cuda>=13.0`.
    """
    tag_cuda = detect_cuda_version(image)
    manifest_cuda = config.GROUP_MIN_CUDA.get(group) if group else None
    if manifest_cuda and tag_cuda and manifest_cuda != tag_cuda:
        log(
            f"min-cuda-version: requested '{manifest_cuda}' overrides "
            f"tag-derived '{tag_cuda}'",
            indent=1,
        )
    elif tag_cuda and not manifest_cuda:
        log(
            f"min-cuda-version: none requested, derived '{tag_cuda}' "
            "from the image tag",
            indent=1,
        )
    elif manifest_cuda and not tag_cuda:
        log(
            f"min-cuda-version: requested '{manifest_cuda}' (tag has "
            "no CUDA marker to derive from)",
            indent=1,
        )
    return manifest_cuda or tag_cuda


def create_pod(
    image: str,
    gpu_id: str,
    name: str,
    *,
    compute_type: str = "GPU",
    group: Optional[str] = None,
    test_jupyter: bool = False,
    test_ports: Optional[list[int]] = None,
    cloud_type: Optional[str] = None,
    data_center_ids: str = "",
    allowed_cuda_versions: Optional[list[str]] = None,
) -> tuple[Optional[str], str, str]:
    """Create a pod via `POST /v2/pods`.

    Returns `(pod_id, kind, detail)`:
      * success      -> (id,   "",            "")
      * no capacity  -> (None, "UNAVAILABLE", detail)
      * retry me     -> (None, "TRANSIENT",   detail)
      * give up      -> (None, "FATAL",       detail)

    compute_type='GPU' targets `gpu_id`; 'CPU' picks a flavor from the CPU
    catalog (v2 requires an explicit `cpu.id` + `vcpuCount`, unlike the old
    CLI which let RunPod choose).

    `cloud_type` overrides `config.CLOUD_TYPE` for this call only — used by
    the CPU-candidate loop to try SECURE then COMMUNITY. `data_center_ids`
    is a csv that, when non-empty, pins placement.

    `allowed_cuda_versions` pins the host to those exact CUDA versions.
    Mutually exclusive with the derived floor: the API rejects
    `allowedCudaVersions` and `minCudaVersion` together with a 400.

    NOTE: v2 has no `terminateAfter`, so there is no server-side deadline
    to fall back on any more — reap-pods.yml is the only backstop.
    """
    disk_gb = config.CPU_DISK_GB if compute_type == "CPU" else config.DISK_GB
    ports = ["22/tcp"]
    if test_jupyter:
        ports.append("8888/http")
    for test_port in test_ports or []:
        spec = f"{test_port}/http"
        if spec not in ports:
            ports.append(spec)

    body: dict = {
        "name": name,
        "image": image,
        "cloud": (cloud_type or config.CLOUD_TYPE).upper(),
        "disk": disk_gb,
        "ports": ports,
        # Injects PUBLIC_KEY from the account's registered keys, which is
        # what makes the SSH readiness probe work.
        "startSsh": True,
    }
    if data_center_ids:
        body["dataCenterIds"] = [
            d.strip() for d in data_center_ids.split(",") if d.strip()
        ]
    if test_jupyter:
        body["env"] = {"JUPYTER_PASSWORD": config.JUPYTER_TEST_PASSWORD}
    if config.REGISTRY_AUTH_ID:
        body["registry"] = config.REGISTRY_AUTH_ID

    if compute_type == "CPU":
        flavor_id, vcpu = pick_cpu_flavor()
        if not flavor_id:
            return None, "FATAL", (
                "no CPU flavor available from GET /v2/catalog/cpus — set "
                "CPU_FLAVOR_ID to choose one explicitly"
            )
        body["cpu"] = {"id": flavor_id, "vcpuCount": vcpu}
    else:
        gpu: dict = {"id": gpu_id, "count": 1}
        if allowed_cuda_versions:
            gpu["allowedCudaVersions"] = list(allowed_cuda_versions)
            log(
                "allowedCudaVersions: pinned to "
                f"{', '.join(allowed_cuda_versions)}",
                indent=1,
            )
        else:
            cuda_version = _resolve_min_cuda(image, group)
            if cuda_version:
                gpu["minCudaVersion"] = cuda_version
        body["gpu"] = gpu

    status, data = api.request("POST", "/pods", body=body, timeout=120)
    if 200 <= status < 300 and isinstance(data, dict):
        pod_id = data.get("id")
        if pod_id:
            return pod_id, "", ""
        return None, "FATAL", "pod create returned no id"
    return None, api.classify_error(status, data), api.error_detail(status, data)


def pod_state(pod_id: str) -> dict:
    """Return the relevant subset of pod state for decision-making.

    `status` is the real observed PodStatus enum (PROVISIONING / STARTING /
    RUNNING / EXITED / ERROR / TERMINATED) — unlike the CLI's
    `desiredStatus`, which was always RUNNING and could only ever detect
    terminal states.

    `ssh.direct` is null until the pod has a machine assignment and a public
    port for `22/tcp`; that transition is the readiness signal we poll for.
    """
    status, data = api.request_with_retries("GET", f"/pods/{pod_id}", timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        return {}
    ssh = data.get("ssh") or {}
    direct = ssh.get("direct") or {}
    return {
        "status": data.get("status"),
        "ssh_ip": direct.get("host") or "",
        "ssh_port": int(direct.get("port") or 0),
        "cuda_version": data.get("cudaVersion") or "",
        "cost": data.get("cost"),
        "data_center": data.get("dataCenterId") or "",
        "started_at": data.get("startedAt"),
        "raw": data,
    }


# ---------------------------------------------------------------------------
# Wait for the pod to become reachable
# ---------------------------------------------------------------------------


# PodStatus values that mean "we will never become RUNNING — stop polling".
_TERMINAL_STATUSES = {"EXITED", "ERROR", "TERMINATED"}


def _log_system_errors(pod_id: str, context: str) -> None:
    """Print host-side API log errors when the pod cannot become ready."""
    errors = system_log_errors(pod_id)
    if errors is None:
        log("system logs unavailable (no API key / request failed)", indent=2)
    elif not errors:
        log(f"system logs: no error markers ({context})", indent=2)
    else:
        log(f"system-log error markers ({context}):", indent=2)
        for line in errors:
            log(f"  {line}", indent=2)


def _print_stall_hint(pod_id: str, elapsed: int) -> None:
    """One-time hint for pods that sit with no SSH endpoint for too long.

    RunPod doesn't surface pull progress via the API, so this points the
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
    pod_status_value: object,
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
    summary = (pod_status_value, host, port, ok)
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
        'RUNNING'   SSH probe to root@<ssh.direct.host>:<port> succeeded —
                    the container's sshd is up, which means it has fully
                    booted and we can trust it as healthy.
        'TERMINAL'  status reached EXITED / ERROR / TERMINATED.
        'TIMEOUT'   SSH never reachable within CREATE_TIMEOUT — pod stuck
                    initializing (capacity issue or image broken).

    SSH probing is the real health-check. We poll `GET /v2/pods/{id}` for
    `ssh.direct` (populated once a machine is allocated and `22/tcp` gets a
    public port), then try `ssh root@host -p port 'echo ready'` until it
    succeeds. A successful SSH means the container booted and sshd started —
    a much stronger signal than any status field.
    """
    start = time.time()
    deadline = start + config.CREATE_TIMEOUT
    last_summary: Optional[tuple] = None
    last_status: Optional[str] = None
    ssh_attempts = 0
    stall_hinted = False  # one-time hint when pod has no ssh endpoint for a while

    while time.time() < deadline:
        st = pod_state(pod_id)
        if not st:
            time.sleep(config.POLL_INTERVAL)
            continue

        pod_status_value = st.get("status")
        host = st.get("ssh_ip") or ""
        port = st.get("ssh_port") or 0
        elapsed = int(time.time() - start)

        if pod_status_value != last_status:
            log(f"t+{elapsed}s status: {pod_status_value}", indent=2)
            last_status = pod_status_value

        if pod_status_value in _TERMINAL_STATUSES:
            _log_system_errors(pod_id, f"pod entered {pod_status_value}")
            return "TERMINAL", (
                f"pod entered {pod_status_value} after {elapsed}s"
            )

        if host and port:
            ssh_attempts += 1
            outcome, last_summary = _probe_ssh_endpoint(
                host, int(port), pod_status_value, elapsed, ssh_attempts,
                last_summary,
            )
            if outcome is not None:
                return outcome
        else:
            summary = (pod_status_value, host, port, False)
            if summary != last_summary:
                log(
                    f"t+{elapsed}s status={pod_status_value!r} "
                    "ssh endpoint not assigned yet",
                    indent=2,
                )
                last_summary = summary
            if elapsed >= config.STALL_HINT_AFTER and not stall_hinted:
                _print_stall_hint(pod_id, elapsed)
                _log_system_errors(pod_id, f"stalled {elapsed}s")
                stall_hinted = True

        time.sleep(config.POLL_INTERVAL)

    _log_system_errors(pod_id, f"timeout after {config.CREATE_TIMEOUT}s")
    return "TIMEOUT", (
        f"SSH endpoint never became reachable in {config.CREATE_TIMEOUT}s "
        f"({ssh_attempts} probes) — pod stuck initializing. Likely causes: "
        "(1) slow/throttled image pull (check UI for pull progress), "
        "(2) Docker Hub rate limit if many parallel pulls of the same image, "
        "(3) host scheduling delay on a saturated DC — "
        "see system-log error markers above (if any)"
    )
