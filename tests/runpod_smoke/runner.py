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
    run_cuda_check,
    run_jupyter_check,
    run_jupyter_proxy_check,
    ssh_probe,
)
from .instances import detect_cuda_version, resolve_gpu_id
from .log import log
from .pod import (
    TRANSIENT_RE,
    UNAVAILABLE_RE,
    cleanup_pod,
    create_pod,
    pod_state,
    register_pod,
    wait_for_running,
)


def test_pair(image: str, instance: str, group: str) -> tuple[str, str]:
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
    is_cpu = instance == config.CPU_INSTANCE_SENTINEL
    if is_cpu:
        gpu_id = ""
        log("attempt: CPU pod (--compute-type CPU, flavor chosen by RunPod)",
            indent=1)
    else:
        gpu_id = resolve_gpu_id(instance)
        cuda = detect_cuda_version(image) or config.GROUP_MIN_CUDA.get(group)
        cuda_note = f", min-cuda={cuda}" if cuda else ""
        log(
            f"attempt: instance='{instance}' (--gpu-id '{gpu_id}'){cuda_note}",
            indent=1,
        )

    # Retry on transient orchestrator errors (5xx, "something went wrong",
    # 502/503/504). These often happen when several workers race for the
    # same scarce GPU at the same instant. We back off and retry a few
    # times before giving up and moving on to the next instance.
    pod_id: Optional[str] = None
    raw = ""
    for attempt in range(1, config.CREATE_RETRIES + 1):
        # New name on each attempt — RunPod may keep a server-side record
        # of rejected names briefly, and unique names also make logs
        # unambiguous.
        name = (
            f"smoketest-{int(time.time())}-"
            f"{threading.get_ident() % 10000:04d}-{attempt}"
        )
        pod_id, raw = create_pod(
            image, gpu_id, name,
            compute_type="CPU" if is_cpu else "GPU",
            group=group,
            test_jupyter=config.GROUP_TEST_JUPYTER.get(group, False),
        )
        if pod_id:
            break
        if UNAVAILABLE_RE.search(raw):
            log(f"instance unavailable, will try next ({raw[:120]})", indent=2)
            return "UNAVAILABLE", ""
        if TRANSIENT_RE.search(raw) and attempt < config.CREATE_RETRIES:
            backoff = config.CREATE_RETRY_BACKOFF * attempt
            log(
                f"transient pod-create error ({raw[:120]}), "
                f"retry {attempt}/{config.CREATE_RETRIES - 1} in {backoff}s",
                indent=2,
            )
            time.sleep(backoff)
            continue
        log(f"pod create failed: {raw[:400]}", indent=2)
        return "CREATE_FAIL", f"pod create failed: {raw[:200].strip()}"

    if not pod_id:
        log(f"pod create failed after {config.CREATE_RETRIES} attempts: {raw[:200]}",
            indent=2)
        return "CREATE_FAIL", (
            f"pod create failed after {config.CREATE_RETRIES} attempts: "
            f"{raw[:200].strip()}"
        )

    register_pod(pod_id)
    log(
        f"pod {pod_id} created, waiting for RUNNING "
        f"(timeout {config.CREATE_TIMEOUT}s)",
        indent=2,
    )

    try:
        state, detail = wait_for_running(pod_id)
        if state != "RUNNING":
            # Distinguish "host never came up" (STUCK — try another instance)
            # from "container actually died" (FAIL — image is broken).
            # TIMEOUT with no SSH endpoint ever assigned is almost always a
            # scheduler/host issue, not the image: a different GPU type
            # lands on a different host pool and usually works.
            st = pod_state(pod_id)
            ever_had_ssh = bool(st.get("ssh_ip") and st.get("ssh_port"))
            if state == "TIMEOUT" and not ever_had_ssh:
                log(
                    f"{state.lower()} -- {detail} -- STUCK (no SSH endpoint "
                    "was ever assigned; trying next instance type)",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "STUCK", ""
            log(f"{state.lower()} -- {detail} -- FAIL", indent=2)
            dump_pod_logs(pod_id)
            return "FAIL", f"pod entered {state} state: {detail}"

        log(f"smoke check passed: {detail}", indent=2)

        # Run the per-group CUDA/GPU functional check. This is the real
        # "does this image actually work" gate — distinct from "did it boot".
        st = pod_state(pod_id)
        host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
        if host and port and cuda_check_command(image):
            log(f"running GPU/CUDA functional check for group '{group}'...", indent=2)
            ok, output = run_cuda_check(host, int(port), image)
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log("cuda check FAILED -- image broken", indent=2)
                dump_pod_logs(pod_id)
                return "FAIL", "CUDA/GPU functional check failed"
            log("cuda check passed", indent=2)

        # Jupyter checks: only when the group opted in via `test_jupyter`.
        # Two stages, both must pass:
        #   1. IN-POD: SSH into the pod and probe 127.0.0.1:8888. Catches
        #      start.sh regressions (e.g. wrong python interpreter for
        #      `-m jupyter`) that don't surface in container stdout.
        #   2. PROXY: from the test machine, hit
        #      https://<pod-id>-8888.proxy.runpod.net/. Catches port-type
        #      mistakes (`8888/tcp` instead of `8888/http`) — proxy never
        #      registers a non-http port, so end users can't reach Jupyter
        #      even though the in-pod check would happily pass.
        if host and port and config.GROUP_TEST_JUPYTER.get(group, False):
            log(
                f"running Jupyter Lab check (in-pod) for group '{group}'...",
                indent=2,
            )
            ok, output = run_jupyter_check(host, int(port))
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log(
                    "jupyter check (in-pod) FAILED -- start.sh did not "
                    "bring up JupyterLab",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "FAIL", "Jupyter Lab check failed (in-pod)"
            log("jupyter check (in-pod) passed", indent=2)

            log(
                f"running Jupyter Lab check (public proxy) for pod "
                f"{pod_id}...",
                indent=2,
            )
            ok, output = run_jupyter_proxy_check(pod_id)
            for line in (output or "").splitlines():
                log(f"  {line}", indent=2)
            if not ok:
                log(
                    "jupyter check (public proxy) FAILED -- port likely "
                    "not exposed as 8888/http",
                    indent=2,
                )
                dump_pod_logs(pod_id)
                return "FAIL", "Jupyter Lab check failed (public proxy)"
            log("jupyter check (public proxy) passed", indent=2)

        # Brief dwell to catch containers that boot, accept SSH, then
        # crash. Most real images hit this in the first ~30s if they're
        # going to crash.
        if config.DWELL_SEC > 0:
            log(f"dwelling {config.DWELL_SEC}s and re-probing SSH...", indent=2)
            time.sleep(config.DWELL_SEC)
            st = pod_state(pod_id)
            host, port = st.get("ssh_ip") or "", st.get("ssh_port") or 0
            if host and port:
                ok, err = ssh_probe(host, int(port), timeout=8)
                if not ok:
                    log(
                        f"ssh probe failed after dwell ({err}) -- "
                        "container crashed -- FAIL",
                        indent=2,
                    )
                    dump_pod_logs(pod_id)
                    return "FAIL", (
                        "container crashed after initial boot "
                        f"({config.DWELL_SEC}s dwell re-probe failed: {err})"
                    )

        dump_pod_logs(pod_id)
        return "PASS", ""
    finally:
        # Always clean up this specific pod, even on exception.
        cleanup_pod(pod_id)


def test_image(
    image: str, instances: list[str], group: str
) -> tuple[str, str, str]:
    """Returns (status, note, instance_used).

    `instance_used` is the GPU display name that produced the terminal
    status. For PASS / FAIL it's the actual instance the test landed on.
    For SKIP (no capacity / all stuck), it's an empty string — the test
    never settled on any one instance.

    Iterates instance types until one PASSes. Stops early on FAIL (real
    image bug — no point trying another GPU). UNAVAILABLE (capacity) and
    STUCK (RunPod gave us a dead host) just move on to the next instance.
    CREATE_FAIL also short-circuits: a non-capacity orchestrator error
    (e.g. bad image tag, registry auth) won't be fixed by another GPU.
    """
    log(f"image: {image}")
    stuck_instances: list[str] = []
    last_create_error = ""
    last_create_inst = ""
    for inst in instances:
        result, detail = test_pair(image, inst, group)
        if result == "PASS":
            return "PASS", "", inst
        if result == "FAIL":
            return (
                "FAIL",
                detail or "container did not stay healthy",
                inst,
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
        # UNAVAILABLE: silently try next
    if last_create_error:
        # We never got past pod-create on any instance and the errors
        # weren't capacity-shortages. Surface the last orchestrator error
        # — this is usually an image / auth / registry problem.
        return "FAIL", last_create_error, last_create_inst
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
                f"RunPod never assigned an SSH endpoint on "
                f"{len(stuck_instances)} instance type(s) — likely a "
                "scheduler issue, try again later"
            ),
            "",
        )
    log(f"all {len(instances)} instances unavailable (no capacity)", indent=1)
    return (
        "SKIP",
        f"no capacity on any of {len(instances)} candidate instance type(s)",
        "",
    )
