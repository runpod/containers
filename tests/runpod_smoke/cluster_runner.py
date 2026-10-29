"""Instant Cluster test orchestration — the cluster counterpart of
runner.test_pair.

  * test_cluster_pair(image, instance, group) — one cluster on one GPU
    type: create it, wait for every member pod, run the checks, delete it.
    Returns the same (status, detail) vocabulary as test_pair, so
    runner.test_image walks GPU types and summarises identically.

Checks, in order, per node then cluster-wide:
  1. SSH readiness on every node (pod.wait_for_running)
  2. hostname matches the cluster rank (node-0 is the head)
  3. CUDA functional check on every node
  4. Jupyter through the public proxy on every node
  5. monitoring: exporters on every node, head-only services only on node-0,
     and Prometheus on the head scraping every node
  6. Grafana on the head through the public proxy (health, token login,
     no anonymous access, datasource query)
  7. image hygiene checks the group opted into, on the head only
  8. container-log error scan, dwell, then SSH re-probe of every node
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import config
from .checks import SshEndpoint, dump_pod_logs, run_simple_check, ssh_probe
from .cluster import (
    ClusterNode,
    cleanup_cluster,
    cluster_gpu_sizes,
    create_cluster,
    pick_gpus_per_node,
    register_cluster,
    wait_for_nodes,
)
from .cluster_checks import (
    head_monitoring_command,
    node_identity_command,
    run_grafana_proxy_check,
    worker_monitoring_command,
)
from .log import log
from .pod import pod_state, wait_for_running
from .runner import (
    _Outcome,
    _classify_non_running,
    _log_attempt_header,
    _run_cuda_step,
    _run_hygiene_steps,
    _run_jupyter_steps,
    _run_log_scan_step,
    _set_host_cuda,
)


def _create_cluster_with_retries(
    image: str, gpu_id: str, group: str, node_count: int, gpus_per_node: int,
) -> tuple[Optional[str], str, str]:
    """(cluster_id, "", "") or (None, UNAVAILABLE | CREATE_FAIL, detail).
    Same retry policy as runner._create_pod_with_retries."""
    raw = ""
    for attempt in range(1, config.CREATE_RETRIES + 1):
        # `smoketest-<epoch>-` is what reap_clusters.py keys on.
        name = (
            f"smoketest-{int(time.time())}-"
            f"{threading.get_ident() % 10000:04d}-{attempt}"
        )
        cluster_id, kind, raw = create_cluster(
            image, gpu_id, name, node_count=node_count,
            gpus_per_node=gpus_per_node, group=group,
        )
        if cluster_id:
            return cluster_id, "", ""
        if kind == "UNAVAILABLE":
            log(f"no cluster capacity, will try next ({raw[:160]})", indent=2)
            return None, "UNAVAILABLE", ""
        if kind == "TRANSIENT" and attempt < config.CREATE_RETRIES:
            backoff = config.CREATE_RETRY_BACKOFF * attempt
            log(
                f"transient cluster-create error ({raw[:120]}), "
                f"retry {attempt}/{config.CREATE_RETRIES - 1} in {backoff}s",
                indent=2,
            )
            time.sleep(backoff)
            continue
        break
    log(f"cluster create failed: {raw[:400]}", indent=2)
    return None, "CREATE_FAIL", f"cluster create failed: {raw[:200].strip()}"


def _resolve_node_shape(group: str, gpu_id: str) -> tuple[Optional[int], int]:
    """(gpus_per_node, node_count); gpus_per_node None = not offered."""
    node_count = config.GROUP_CLUSTER_NODES.get(group, config.DEFAULT_CLUSTER_NODES)
    requested = config.GROUP_CLUSTER_GPUS_PER_NODE.get(group, 0)
    offered = cluster_gpu_sizes(gpu_id)
    if offered is None:
        # Catalog unreadable: try the request as given and let createCluster
        # be the judge rather than skipping a GPU we know nothing about.
        gpus = requested or 1
        log(f"cluster GPU catalog unavailable, asking for {gpus} GPU(s)/node", indent=2)
        return gpus, node_count
    gpus = pick_gpus_per_node(requested, offered)
    if gpus is None:
        log(
            f"'{gpu_id}' offers no cluster nodes with "
            f"{requested or 'any'} GPU(s) (offered: {offered or 'none'})",
            indent=2,
        )
    return gpus, node_count


def _fail(node: ClusterNode, image: str, detail: str) -> _Outcome:
    log(f"{node.hostname}: {detail} -- FAIL", indent=2)
    dump_pod_logs(node.pod_id, image)
    return "FAIL", f"{node.hostname}: {detail}"


def _run_check(
    node: ClusterNode, endpoint: SshEndpoint, label: str, command: str,
    timeout: int, image: str,
) -> Optional[_Outcome]:
    log(f"{node.hostname}: running {label} check...", indent=2)
    ok, output = run_simple_check(endpoint, command, timeout=timeout)
    for line in (output or "").splitlines():
        log(f"  {line}", indent=2)
    if ok:
        log(f"{node.hostname}: {label} check passed", indent=2)
        return None
    return _fail(node, image, f"{label} check failed")


def _node_steps(
    node: ClusterNode, endpoint: SshEndpoint, image: str, group: str,
) -> Optional[_Outcome]:
    """Checks that hold for every member pod."""
    outcome = _run_check(
        node, endpoint, "hostname/rank", node_identity_command(node.idx),
        60, image,
    )
    if outcome is not None:
        return outcome
    outcome = _run_cuda_step(endpoint, image, group, node.pod_id)
    if outcome is None:
        outcome = _run_jupyter_steps(endpoint, node.pod_id, image, group)
    if outcome is not None:
        return outcome[0], f"{node.hostname}: {outcome[1]}"
    return None


def _monitoring_steps(
    nodes: list[ClusterNode], endpoints: dict[str, SshEndpoint], image: str,
) -> Optional[_Outcome]:
    """Workers first: a worker whose exporters never started is the most
    precise explanation for the head's target check failing."""
    wait = config.MONITORING_WAIT_TIMEOUT
    dcgm = config.CLUSTER_REQUIRE_DCGM
    for node in nodes:
        if node.is_head:
            continue
        outcome = _run_check(
            node, endpoints[node.pod_id], "worker monitoring",
            worker_monitoring_command(wait, dcgm), wait + 60, image,
        )
        if outcome is not None:
            return outcome
    head = nodes[0]
    # Up to three waits in a row: supervisord, Grafana health, scrapes.
    outcome = _run_check(
        head, endpoints[head.pod_id], "head monitoring stack",
        head_monitoring_command(len(nodes), wait, dcgm), 3 * wait + 60, image,
    )
    if outcome is not None:
        return outcome

    log(f"{head.hostname}: running Grafana check (public proxy)...", indent=2)
    ok, output = run_grafana_proxy_check(head.pod_id)
    for line in output.splitlines():
        log(f"  {line}", indent=2)
    if not ok:
        return _fail(head, image, "Grafana not reachable/healthy via proxy on "
                     f":{config.GRAFANA_PORT}")
    log(f"{head.hostname}: Grafana check passed", indent=2)
    return None


def _dwell_steps(
    nodes: list[ClusterNode], endpoints: dict[str, SshEndpoint], image: str,
) -> Optional[_Outcome]:
    """One dwell for the whole cluster, then every node must still answer."""
    if config.DWELL_SEC <= 0:
        return None
    log(f"dwelling {config.DWELL_SEC}s and re-probing every node...", indent=2)
    time.sleep(config.DWELL_SEC)
    for node in nodes:
        ok, err = ssh_probe(endpoints[node.pod_id], timeout=8)
        if not ok:
            return _fail(node, image, f"container crashed after initial boot "
                         f"({config.DWELL_SEC}s dwell re-probe failed: {err})")
    for node in nodes:
        outcome = _run_log_scan_step(node.pod_id, image)
        if outcome is not None:
            return outcome[0], f"{node.hostname}: {outcome[1]}"
    return None


def _run_cluster_checks(
    nodes: list[ClusterNode], image: str, group: str,
) -> _Outcome:
    endpoints: dict[str, SshEndpoint] = {}
    # Members boot in parallel, so waiting on them in turn costs only the
    # slowest boot, not the sum: one shared deadline for all of them.
    deadline = time.time() + config.CLUSTER_BOOT_TIMEOUT
    for node in nodes:
        log(f"{node.hostname}: waiting for pod {node.pod_id} (ip {node.ip or '?'})", indent=2)
        budget = max(int(deadline - time.time()), config.POLL_INTERVAL)
        state, detail, endpoint = wait_for_running(node.pod_id, timeout=budget)
        if state != "RUNNING":
            status, why = _classify_non_running(state, detail, node.pod_id, image)
            return status, (f"{node.hostname}: {why}" if why else why)
        assert endpoint is not None
        log(f"{node.hostname}: {detail}", indent=2)
        endpoints[node.pod_id] = endpoint

    host_cuda = pod_state(nodes[0].pod_id).get("cuda_version") or ""
    if host_cuda:
        _set_host_cuda(host_cuda)
        log(f"host CUDA: {host_cuda}", indent=2)

    for node in nodes:
        outcome = _node_steps(node, endpoints[node.pod_id], image, group)
        if outcome is not None:
            return outcome
    outcome = _monitoring_steps(nodes, endpoints, image)
    if outcome is not None:
        return outcome
    head = nodes[0]
    outcome = _run_hygiene_steps(endpoints[head.pod_id], head.pod_id, image, group)
    if outcome is not None:
        return outcome
    for node in nodes:
        outcome = _run_log_scan_step(node.pod_id, image)
        if outcome is not None:
            return outcome[0], f"{node.hostname}: {outcome[1]}"
    outcome = _dwell_steps(nodes, endpoints, image)
    if outcome is not None:
        return outcome
    return "PASS", ""


def test_cluster_pair(
    image: str, instance: str, group: str, cuda_pin: str = "", cloud: str = "",
) -> _Outcome:
    """One Instant Cluster attempt on GPU type `instance`. Same statuses as
    runner.test_pair. `cuda_pin` and `cloud` are accepted for signature
    parity and ignored: clusters are secure-cloud only and have no CUDA axis.
    """
    del cuda_pin, cloud
    _set_host_cuda("")
    _, gpu_id = _log_attempt_header(image, instance, group)
    gpus_per_node, node_count = _resolve_node_shape(group, gpu_id)
    if gpus_per_node is None:
        return "UNAVAILABLE", ""
    log(
        f"cluster: {node_count} node(s) x {gpus_per_node} GPU(s), "
        f"env={config.RUNPOD_ENV}",
        indent=1,
    )

    cluster_id, early, early_detail = _create_cluster_with_retries(
        image, gpu_id, group, node_count, gpus_per_node,
    )
    if early:
        return early, early_detail
    assert cluster_id is not None
    register_cluster(cluster_id)
    log(f"cluster {cluster_id} created, waiting for {node_count} member pods", indent=2)
    try:
        nodes, why = wait_for_nodes(cluster_id, node_count)
        if nodes is None:
            log(f"{why} -- STUCK (trying next instance type)", indent=2)
            return "STUCK", ""
        log(
            "members: " + ", ".join(f"{n.hostname}={n.pod_id}" for n in nodes),
            indent=2,
        )
        return _run_cluster_checks(nodes, image, group)
    finally:
        cleanup_cluster(cluster_id)
