"""Per-image test orchestration.

Two functions, both called from `test_images.py:main`:

  * test_pair(image, instance, group) — one create-attempt against one GPU
    type. Owns retry-on-transient and the FAIL/UNAVAILABLE/STUCK/CREATE_FAIL
    classification of a single pod's lifecycle.

  * test_image(image, instances, group) — iterate test_pair across all
    candidate instance types until something settles. Returns the final
    PASS / FAIL / SKIP outcome plus the instance it landed on.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import config
from .checks import (
    cuda_check_command,
    dump_pod_logs,
    fetch_pod_cuda_version,
    host_incompatibility,
    run_cuda_check,
    run_jupyter_check,
    run_jupyter_proxy_check,
    run_port_check,
    run_port_proxy_check,
    scan_pod_logs_for_errors,
    ssh_probe,
)
from .comfyui import probe_comfyui_alive, run_comfyui_check
from .instances import detect_cuda_version, resolve_gpu_id
from .log import log, set_worker_context
from .pod import (
    cleanup_pod,
    create_pod,
    pod_state,
    register_pod,
    wait_for_running,
)


_Outcome = tuple[str, str]

# test_pair records the host's CUDA version here instead of returning it, so
# the ~15 outcome returns in that function keep their 2-tuple shape.
# test_image reads it on the same thread right after test_pair returns.
# Stored bare ('13.0') — the 'CUDA ' prefix is added at render time so the
# JSON report can carry the raw value.
_thread_local = threading.local()


def _set_host_cuda(version: str) -> None:
    _thread_local.host_cuda = version


def _take_host_cuda() -> str:
    """Read and clear the version left by the last test_pair on this thread."""
    version = getattr(_thread_local, "host_cuda", "") or ""
    _thread_local.host_cuda = ""
    return version


def _log_attempt_header(
    image: str, instance: str, group: str, cuda_pin: str = "",
    cloud: str = "",
) -> tuple[bool, str]:
    """Log the per-attempt header line and resolve the gpu_id.

    Returns (is_cpu, gpu_id). CPU attempts get an empty gpu_id since
    CPU pods carry a `cpu` block instead of a `gpu` one, so no gpu_id.
    Per-candidate (cloud_type, data_center_ids) is looked up separately
    by the caller via `config.cpu_candidate_for(instance)`."""
    if config.is_cpu_instance(instance):
        candidate = config.cpu_candidate_for(instance)
        dc_note = (
            f", --data-center-ids {candidate.data_center_ids}"
            if candidate.data_center_ids
            else ""
        )
        log(
            f"attempt: CPU pod '{instance}' "
            f"(--cloud-type {candidate.cloud_type}{dc_note})",
            indent=1,
        )
        return True, ""
    gpu_id = resolve_gpu_id(instance)
    if cuda_pin:
        cuda_note = f", cuda-pinned={cuda_pin}"
    else:
        # Same precedence as create_pod: explicit request wins, tag is fallback.
        cuda = config.GROUP_MIN_CUDA.get(group) or detect_cuda_version(image)
        cuda_note = f", min-cuda={cuda}" if cuda else ""
    cloud_note = f", cloud={cloud}" if cloud and len(config.CLOUD_TYPES) > 1 else ""
    log(
        f"attempt: instance='{instance}' (--gpu-id '{gpu_id}')"
        f"{cuda_note}{cloud_note}",
        indent=1,
    )
    return False, gpu_id


def _create_pod_with_retries(
    image: str, instance: str, gpu_id: str, is_cpu: bool, group: str,
    cuda_pin: str = "", cloud: str = "",
) -> tuple[Optional[str], str, str]:
    """Drive `create_pod` through the transient-error retry budget.

    Returns (pod_id, early_outcome, detail):
      - on success     -> (pod_id, "", "")
      - on UNAVAILABLE -> (None, "UNAVAILABLE", "")  # capacity, try next instance
      - on CREATE_FAIL -> (None, "CREATE_FAIL", error)  # non-transient orchestrator
                                                        # error, another GPU won't help

    Transient errors (5xx, "something went wrong", 502/503/504) often happen
    when several workers race for the same scarce GPU at the same instant.
    We back off and retry a few times before falling through to CREATE_FAIL.
    """
    # CPU candidate (cloud_type, data_center_ids) is encoded in the
    # instance label (see config.CPU_CANDIDATES). GPU jobs carry the tier
    # they were planned against, since a multi-tier sweep runs both from one
    # pool and the global config.CLOUD_TYPE no longer identifies either.
    cpu_candidate = (
        config.cpu_candidate_for(instance) if is_cpu else None
    )
    cloud_override = (
        cpu_candidate.cloud_type if cpu_candidate else (cloud or None)
    )
    dc_ids = cpu_candidate.data_center_ids if cpu_candidate else ""
    raw = ""
    for attempt in range(1, config.CREATE_RETRIES + 1):
        # New name on each attempt — RunPod may keep a server-side record
        # of rejected names briefly, and unique names also make logs
        # unambiguous.
        name = (
            f"smoketest-{int(time.time())}-"
            f"{threading.get_ident() % 10000:04d}-{attempt}"
        )
        test_ports = list(config.GROUP_TEST_PORTS.get(group) or [])
        if config.GROUP_TEST_COMFYUI.get(group, False):
            test_ports.append(config.COMFYUI_PORT)
        pod_id, kind, raw = create_pod(
            image, gpu_id, name,
            compute_type="CPU" if is_cpu else "GPU",
            group=group,
            test_jupyter=config.GROUP_TEST_JUPYTER.get(group, False),
            test_ports=test_ports,
            cloud_type=cloud_override,
            data_center_ids=dc_ids,
            allowed_cuda_versions=[cuda_pin] if cuda_pin else None,
        )
        if pod_id:
            return pod_id, "", ""
        if kind == "UNAVAILABLE":
            log(f"instance unavailable, will try next ({raw[:120]})", indent=2)
            return None, "UNAVAILABLE", ""
        if kind == "TRANSIENT" and attempt < config.CREATE_RETRIES:
            backoff = config.CREATE_RETRY_BACKOFF * attempt
            log(
                f"transient pod-create error ({raw[:120]}), "
                f"retry {attempt}/{config.CREATE_RETRIES - 1} in {backoff}s",
                indent=2,
            )
            time.sleep(backoff)
            continue
        log(f"pod create failed: {raw[:400]}", indent=2)
        return None, "CREATE_FAIL", f"pod create failed: {raw[:200].strip()}"

    # Theoretically unreachable: the loop body returns on every path. This
    # tail return only fires if a future edit breaks that invariant — keep
    # it so the function still classifies cleanly instead of returning None.
    log(
        f"pod create failed after {config.CREATE_RETRIES} attempts: {raw[:200]}",
        indent=2,
    )
    return None, "CREATE_FAIL", (
        f"pod create failed after {config.CREATE_RETRIES} attempts: "
        f"{raw[:200].strip()}"
    )


def _over_candidates(count: int) -> str:
    """Suffix naming how many candidates were tried, or '' for exactly one.

    With a CUDA axis or check_all_gpu every job carries a single candidate,
    and "no capacity on any of 1 candidate instance type(s)" reads like a
    bug. Saying nothing is right there: the row already names the GPU.
    """
    if count <= 1:
        return ""
    return f" on any of {count} candidate instance types"


def _classify_non_running(
    state: str, detail: str, pod_id: str, image: str,
) -> _Outcome:
    """Map a non-RUNNING terminal state to STUCK or FAIL.

    TIMEOUT with no SSH endpoint ever assigned is almost always a
    scheduler/host issue, not the image: a different GPU type lands on
    a different host pool and usually works. Anything else (EXITED,
    TERMINATED, FAILED, RUNNING-then-died) is a container problem — the
    image is broken, another GPU won't help.

    A container-init rejection overrides that heuristic. It looks identical
    from the outside — no SSH, no RUNNING — but it is a verdict about the
    image, so it must not be reported as a retryable host problem."""
    st = pod_state(pod_id)
    ever_had_ssh = bool(st.get("ssh_ip") and st.get("ssh_port"))
    # Dumped before the verdict so the classification can use its findings.
    sys_errors = dump_pod_logs(pod_id, image)
    blocker = host_incompatibility(sys_errors)
    if blocker:
        log(
            f"{state.lower()} -- container init rejected the image "
            f"({blocker}) -- FAIL (deterministic; not retrying other "
            "instance types)",
            indent=2,
        )
        return "FAIL", f"container init rejected the image: {blocker}"
    if state == "TIMEOUT" and not ever_had_ssh:
        log(
            f"{state.lower()} -- {detail} -- STUCK (no SSH endpoint "
            "was ever assigned; trying next instance type)",
            indent=2,
        )
        return "STUCK", ""
    log(f"{state.lower()} -- {detail} -- FAIL", indent=2)
    return "FAIL", f"pod entered {state} state: {detail}"


def _run_cuda_step(
    host: str, port: int, image: str, group: str, pod_id: str,
) -> Optional[_Outcome]:
    """Per-group CUDA/GPU functional check — the real "does this image
    actually work" gate, distinct from "did it boot". Returns the FAIL
    outcome on a broken image, None if the check was skipped (no SSH /
    no check command for this image) or passed."""
    if not (host and port and cuda_check_command(image)):
        return None
    log(f"running GPU/CUDA functional check for group '{group}'...", indent=2)
    ok, output = run_cuda_check(host, port, image)
    for line in (output or "").splitlines():
        log(f"  {line}", indent=2)
    if not ok:
        log("cuda check FAILED -- image broken", indent=2)
        dump_pod_logs(pod_id, image)
        return "FAIL", "CUDA/GPU functional check failed"
    log("cuda check passed", indent=2)
    return None


def _run_jupyter_steps(
    host: str, port: int, pod_id: str, image: str, group: str,
) -> Optional[_Outcome]:
    """Jupyter checks: only when the group opted in via `test_jupyter`.

    Checks the public proxy first — the end-user path. SSH only diagnoses
    a proxy failure, so a healthy public endpoint avoids redundant work."""
    if not (host and port and config.GROUP_TEST_JUPYTER.get(group, False)):
        return None

    log(
        f"running Jupyter Lab check (public proxy) for pod {pod_id}...",
        indent=2,
    )
    ok, output = run_jupyter_proxy_check(pod_id)
    for line in (output or "").splitlines():
        log(f"  {line}", indent=2)
    if ok:
        log("jupyter check (public proxy) passed — in-pod check skipped", indent=2)
        return None

    log(
        "jupyter check (public proxy) FAILED — running in-pod check "
        "to diagnose...",
        indent=2,
    )
    ok, output = run_jupyter_check(host, port)
    for line in (output or "").splitlines():
        log(f"  {line}", indent=2)
    if ok:
        log(
            "in-pod check passed -> Jupyter is up but unreachable via "
            "proxy — port likely not exposed as 8888/http",
            indent=2,
        )
        dump_pod_logs(pod_id, image)
        return "FAIL", "Jupyter reachable in-pod but not via proxy"
    log("in-pod check FAILED too -> JupyterLab did not start", indent=2)
    dump_pod_logs(pod_id, image)
    return "FAIL", "Jupyter Lab not running (proxy + in-pod failed)"


def _check_port_proxy_first(
    host: str, port: int, pod_id: str, test_port: int, label: str,
) -> Optional[_Outcome]:
    """Check public reachability first; use SSH only to diagnose failure."""
    log(
        f"running {label} check (public proxy) for pod {pod_id}...",
        indent=2,
    )
    ok, output = run_port_proxy_check(pod_id, test_port)
    for line in output.splitlines():
        log(f"  {line}", indent=2)
    if ok:
        log(f"{label} check (public proxy) passed — in-pod check skipped", indent=2)
        return None

    log(
        f"{label} check (public proxy) FAILED — running in-pod check "
        "to diagnose...",
        indent=2,
    )
    ok, detail = run_port_check(
        host, port, test_port, on_line=lambda line: log(f"  {line}", indent=2)
    )
    if ok:
        failure = f"{label}: reachable in-pod but not via proxy"
    else:
        failure = f"{label}: service not responding (proxy + in-pod)"
        if detail:
            failure += f" — {detail}"
    log(f"{failure} -- FAIL", indent=2)
    return "FAIL", failure


def _run_port_steps(
    host: str, port: int, pod_id: str, image: str, group: str,
) -> Optional[_Outcome]:
    """Run each generic `test_ports` check."""
    for test_port in config.GROUP_TEST_PORTS.get(group) or []:
        outcome = _check_port_proxy_first(
            host, port, pod_id, test_port, f"port {test_port}",
        )
        if outcome is not None:
            dump_pod_logs(pod_id, image)
            return outcome
    return None


def _run_comfyui_steps(
    host: str, port: int, pod_id: str, image: str, group: str,
) -> Optional[_Outcome]:
    """Run the labelled ComfyUI proxy-first reachability smoke."""
    if not (host and port and config.GROUP_TEST_COMFYUI.get(group, False)):
        return None
    outcome = _check_port_proxy_first(
        host, port, pod_id, config.COMFYUI_PORT, "ComfyUI reachability",
    )
    if outcome is not None:
        dump_pod_logs(pod_id, image)
        return outcome
    if not config.GROUP_TEST_COMFYUI_FUNCTIONAL.get(group, False):
        return None

    log("running ComfyUI functional check (via proxy)...", indent=2)
    ok, detail = run_comfyui_check(
        pod_id,
        on_line=lambda line: log(f"  {line}", indent=2),
        save_dir=config.COMFYUI_SAVE_DIR,
        tag=pod_id,
    )
    if ok:
        log("ComfyUI functional check passed", indent=2)
        return None
    log(f"ComfyUI functional check FAILED -- {detail}", indent=2)
    dump_pod_logs(pod_id, image)
    return "FAIL", f"ComfyUI functional check failed: {detail[:160]}"


def _run_log_scan_step(pod_id: str, image: str) -> Optional[_Outcome]:
    """Scan the REST API container-log backfill for boot error markers."""
    if not config.LOG_ERROR_SCAN:
        return None
    log("scanning container logs for error markers (via API)...", indent=2)
    ok, report = scan_pod_logs_for_errors(pod_id)
    for line in report.splitlines():
        log(f"  {line}", indent=2)
    if ok:
        log("log scan passed", indent=2)
        return None

    detail = (
        "log scan unverified — log API returned no container logs"
        if report.startswith("log scan UNVERIFIED")
        else "error markers found in container logs"
    )
    log(f"log scan FAILED -- {detail}", indent=2)
    dump_pod_logs(pod_id, image)
    return "FAIL", detail


def _run_dwell_step(pod_id: str, image: str) -> Optional[_Outcome]:
    """Brief dwell to catch containers that boot, accept SSH, then crash.
    Most real images hit this in the first ~30s if they're going to crash.
    Returns FAIL outcome on a post-boot crash, None on skip / pass."""
    if config.DWELL_SEC <= 0:
        return None
    log(f"dwelling {config.DWELL_SEC}s and re-probing SSH...", indent=2)
    time.sleep(config.DWELL_SEC)
    st = pod_state(pod_id)
    host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
    if not (host and port):
        return None
    ok, err = ssh_probe(host, int(port), timeout=8)
    if ok:
        return None
    log(
        f"ssh probe failed after dwell ({err}) -- "
        "container crashed -- FAIL",
        indent=2,
    )
    dump_pod_logs(pod_id, image)
    return "FAIL", (
        "container crashed after initial boot "
        f"({config.DWELL_SEC}s dwell re-probe failed: {err})"
    )


def _run_post_dwell_steps(
    pod_id: str, image: str, group: str,
) -> Optional[_Outcome]:
    """Re-probe ComfyUI and scan logs after the dwell window."""
    if config.DWELL_SEC <= 0:
        return None
    if (
        config.GROUP_TEST_COMFYUI.get(group, False)
        or config.GROUP_TEST_COMFYUI_FUNCTIONAL.get(group, False)
    ):
        log("re-probing ComfyUI after dwell...", indent=2)
        ok, detail = probe_comfyui_alive(pod_id)
        if not ok:
            log(
                f"ComfyUI re-probe FAILED after dwell ({detail})",
                indent=2,
            )
            dump_pod_logs(pod_id, image)
            return "FAIL", (
                f"ComfyUI stopped answering during the {config.DWELL_SEC}s "
                f"dwell (post-dwell probe: {detail})"
            )
        log(f"ComfyUI re-probe passed ({detail})", indent=2)
    log("re-scanning container logs after dwell...", indent=2)
    return _run_log_scan_step(pod_id, image)


def test_pair(
    image: str, instance: str, group: str, cuda_pin: str = "",
    cloud: str = "",
) -> _Outcome:
    """Returns (status, detail). Statuses:
        'PASS'         — image booted, CUDA check OK, survived dwell
        'FAIL'         — pod was created and the CONTAINER itself proved
                         broken (crashed, CUDA failed, terminal state).
                         Moving to another GPU won't help, the image is bad.
                         `detail` describes which check failed.
        'CREATE_FAIL'  — pod-create returned a non-capacity, non-transient
                         error (bad image tag, registry auth, malformed
                         request, etc.). Like FAIL — another GPU won't fix
                         it. Distinct so the summary doesn't mis-attribute
                         the failure to the container. `detail` is the raw
                         orchestrator error.
        'UNAVAILABLE'  — RunPod has no capacity for this instance — try next
        'STUCK'        — pod was created but RunPod never assigned an SSH
                         endpoint within CREATE_TIMEOUT. Almost always a bad
                         host in the scheduler pool, not an image bug — caller
                         should try a different instance type.

    `group` is the manifest section name (e.g. 'pytorch', 'base_gpu') and
    is used to select the appropriate GPU/CUDA functional check."""
    # Clear first so a label from a previous instance can't leak into an
    # attempt that never reaches the probe (UNAVAILABLE, STUCK).
    _set_host_cuda("")
    is_cpu, gpu_id = _log_attempt_header(image, instance, group, cuda_pin, cloud)

    pod_id, early, early_detail = _create_pod_with_retries(
        image, instance, gpu_id, is_cpu, group, cuda_pin, cloud,
    )
    if early:
        return early, early_detail
    # _create_pod_with_retries' contract: when `early` is empty, pod_id is
    # guaranteed non-None. Assert so the type checker can narrow.
    assert pod_id is not None

    register_pod(pod_id)
    log(
        f"pod {pod_id} created, waiting for RUNNING "
        f"(timeout {config.CREATE_TIMEOUT}s)",
        indent=2,
    )

    try:
        state, wait_detail = wait_for_running(pod_id)
        if state != "RUNNING":
            return _classify_non_running(state, wait_detail, pod_id, image)

        log(f"smoke check passed: {wait_detail}", indent=2)
        st = pod_state(pod_id)
        host = st.get("ssh_ip") or ""
        port = int(st.get("ssh_port") or 0)

        # pod_state already carries cudaVersion, so the common path costs no
        # extra request. It is nullable until the scheduler has assigned a
        # machine, hence the retrying fallback.
        host_cuda = st.get("cuda_version") or fetch_pod_cuda_version(pod_id)
        if host_cuda:
            _set_host_cuda(host_cuda)
            log(f"host CUDA: {host_cuda}", indent=2)

        # Sequence the checks. Each returns None on pass/skip, or a FAIL
        # outcome to surface to the caller. Kept as straight-line code
        # (no fancy abstraction) so the failure points stay easy to read
        # in stack traces / logs.
        outcome = _run_cuda_step(host, port, image, group, pod_id)
        if outcome is not None:
            return outcome
        outcome = _run_jupyter_steps(host, port, pod_id, image, group)
        if outcome is not None:
            return outcome
        outcome = _run_port_steps(host, port, pod_id, image, group)
        if outcome is not None:
            return outcome
        outcome = _run_comfyui_steps(host, port, pod_id, image, group)
        if outcome is not None:
            return outcome
        outcome = _run_log_scan_step(pod_id, image)
        if outcome is not None:
            return outcome
        outcome = _run_dwell_step(pod_id, image)
        if outcome is not None:
            return outcome
        outcome = _run_post_dwell_steps(pod_id, image, group)
        if outcome is not None:
            return outcome

        dump_pod_logs(pod_id, image)
        return "PASS", ""
    finally:
        # Always clean up this specific pod, even on exception.
        cleanup_pod(pod_id)


def test_image(
    image: str, instances: list[str], group: str, cuda_pin: str = "",
    cloud: str = "",
) -> tuple[str, str, str, str]:
    """Returns (status, note, instance_used, host_cuda).

    `instance_used` is the GPU display name that produced the terminal
    status. For PASS / FAIL it's the actual instance the test landed on.
    For SKIP (no capacity / all stuck), it's an empty string — the test
    never settled on any one instance.

    `host_cuda` is the CUDA version the pod actually landed on, or '' when no
    pod ever booted (SKIP) or the host isn't NVIDIA.

    Iterates instance types until one PASSes. Stops early on FAIL (real
    image bug — no point trying another GPU). UNAVAILABLE (capacity) and
    STUCK (RunPod gave us a dead host) just move on to the next instance.
    CREATE_FAIL also short-circuits: a non-capacity orchestrator error
    (e.g. bad image tag, registry auth) won't be fixed by another GPU.
    """
    log(f"image: {image}")
    stuck_instances: list[str] = []
    unavailable_instances: list[str] = []
    last_create_error = ""
    last_create_inst = ""
    for inst in instances:
        set_worker_context(inst)
        try:
            result, detail = test_pair(image, inst, group, cuda_pin, cloud)
        finally:
            set_worker_context(None)
        host_cuda = _take_host_cuda()
        if result == "PASS":
            return "PASS", "", inst, host_cuda
        if result == "FAIL":
            return (
                "FAIL",
                detail or "container did not stay healthy",
                inst,
                host_cuda,
            )
        if result == "CREATE_FAIL":
            # Last create error is most informative — capacity-shortage 5xx
            # would have been UNAVAILABLE, so this is a genuine orchestrator
            # rejection. Try one more instance in case it's instance-specific,
            # but remember the error in case all fail.
            last_create_error = detail
            last_create_inst = inst
            continue
        if result == "STUCK":
            stuck_instances.append(inst)
        if result == "UNAVAILABLE":
            unavailable_instances.append(inst)
    if last_create_error:
        # We never got past pod-create on any instance and the errors
        # weren't capacity-shortages. Surface the last orchestrator error
        # — this is usually an image / auth / registry problem.
        return "FAIL", last_create_error, last_create_inst, ""
    if stuck_instances:
        # We tried every instance and RunPod never gave us a working host
        # on any of them — surface that distinctly from "no capacity at
        # all".
        log(
            f"all {len(instances)} instances either unavailable or stuck "
            f"(stuck: {stuck_instances})",
            indent=1,
        )
        return (
            "SKIP",
            (
                "RunPod never assigned an SSH endpoint"
                + _over_candidates(len(stuck_instances))
                + " — likely a scheduler issue, try again later"
            ),
            ", ".join(stuck_instances),
            "",
        )
    log(f"all {len(instances)} instances unavailable (no capacity)", indent=1)
    return (
        "SKIP",
        "no capacity" + _over_candidates(len(instances)),
        ", ".join(unavailable_instances),
        "",
    )
