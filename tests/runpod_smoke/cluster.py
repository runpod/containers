"""Instant Cluster creation, member discovery and signal-safe teardown.

REST API v2 has no cluster endpoints, so the lifecycle goes through GraphQL
(`createCluster` / `myself.cluster` / `deleteCluster`, see api.graphql). The
member pods are ordinary pods once they exist, so readiness, SSH and log
diagnostics reuse pod.py and checks.py unchanged.

Owns `ACTIVE_CLUSTER_IDS`, the cluster counterpart of pod.ACTIVE_POD_IDS.
Its sweep is registered as a pod.py cleanup hook at import time, so the one
atexit / SIGINT / SIGTERM path tears down clusters before stray pods.
"""

from __future__ import annotations

import threading
import time
from typing import NamedTuple, Optional

from . import api, config
from .instances import detect_cuda_version
from .log import log
from .pod import register_cleanup_hook


class ClusterNode(NamedTuple):
    """One member pod. `idx` is the cluster rank: 0 is the head node, which
    the image recognises by its `node-0` hostname."""

    pod_id: str
    idx: int
    ip: str = ""

    @property
    def is_head(self) -> bool:
        return self.idx == 0

    @property
    def hostname(self) -> str:
        return f"node-{self.idx}"


# ---------------------------------------------------------------------------
# Active-cluster tracking + signal-safe cleanup
# ---------------------------------------------------------------------------

ACTIVE_CLUSTER_IDS: set[str] = set()
_active_clusters_lock = threading.Lock()


def register_cluster(cluster_id: str) -> None:
    with _active_clusters_lock:
        ACTIVE_CLUSTER_IDS.add(cluster_id)


def unregister_cluster(cluster_id: str) -> None:
    with _active_clusters_lock:
        ACTIVE_CLUSTER_IDS.discard(cluster_id)


_DELETE_CLUSTER = """
mutation DeleteCluster($input: DeleteClusterInput!) {
  deleteCluster(input: $input)
}
"""


def delete_cluster(cluster_id: str) -> tuple[bool, str]:
    """Delete the cluster and every member pod. An already-gone cluster
    counts as success, so a retried or doubled teardown stays quiet."""
    status, data = 0, None
    for attempt in range(1, 4):
        status, data = api.graphql(
            _DELETE_CLUSTER, {"input": {"id": cluster_id}}, timeout=60,
        )
        if 200 <= status < 300:
            return True, ""
        detail = api.error_detail(status, data)
        if "not found" in detail.lower():
            return True, ""
        if api.classify_error(status, data) != "TRANSIENT":
            break
        time.sleep(3 * attempt)
    return False, api.error_detail(status, data)


def cleanup_cluster(cluster_id: str) -> None:
    if not cluster_id:
        return
    log(f"Cleaning up cluster {cluster_id}...")
    ok, detail = delete_cluster(cluster_id)
    if not ok:
        # Loud: a leaked cluster bills every node until reap_clusters.py
        # (or a human) deletes it.
        log(f"  WARNING: could not delete cluster {cluster_id}: {detail}")
    unregister_cluster(cluster_id)


def cleanup_all_clusters() -> None:
    with _active_clusters_lock:
        leftover = list(ACTIVE_CLUSTER_IDS)
    if not leftover:
        return
    log(f"Cleaning up {len(leftover)} leftover cluster(s)...")
    for cid in leftover:
        cleanup_cluster(cid)


register_cleanup_hook(cleanup_all_clusters)


# ---------------------------------------------------------------------------
# Catalog: which node sizes a GPU type offers
# ---------------------------------------------------------------------------

_GPU_SIZES = """
query ClusterGpuSizes {
  gpuTypes { id nodeGroupGpuSizes clusterPrice }
}
"""


class ClusterGpu(NamedTuple):
    gpu_id: str
    sizes: list[int]          # GPUs per node on offer, ascending
    price: float              # static per-GPU cluster price, for ordering


_catalog: list[ClusterGpu] = []
_catalog_lock = threading.Lock()


def parse_cluster_catalog(gpu_types: object) -> list[ClusterGpu]:
    """GPU types offered for Instant Clusters, cheapest first. Types with no
    node sizes are not offered for clusters at all and are dropped, as is
    the catalog's `unknown` placeholder."""
    out: list[ClusterGpu] = []
    for entry in gpu_types if isinstance(gpu_types, list) else []:
        if not isinstance(entry, dict):
            continue
        gpu_id = str(entry.get("id") or "")
        sizes = sorted(
            int(s) for s in entry.get("nodeGroupGpuSizes") or []
            if isinstance(s, (int, float)) and s > 0
        )
        if not gpu_id or gpu_id == "unknown" or not sizes:
            continue
        price = entry.get("clusterPrice")
        out.append(ClusterGpu(
            gpu_id, sizes, float(price) if isinstance(price, (int, float)) else 0.0,
        ))
    return sorted(out, key=lambda g: (g.price * g.sizes[0], g.gpu_id))


def cluster_catalog() -> Optional[list[ClusterGpu]]:
    """Cached cluster GPU catalog, or None if it could not be read."""
    with _catalog_lock:
        if not _catalog:
            status, data = api.graphql(_GPU_SIZES, timeout=30)
            if not (200 <= status < 300) or not isinstance(data, dict):
                api.log_error("cluster GPU catalog", status, data, indent=1)
                return None
            _catalog[:] = parse_cluster_catalog(data.get("gpuTypes"))
        return list(_catalog)


def cluster_gpu_sizes(gpu_id: str) -> Optional[list[int]]:
    """GPUs-per-node values Instant Clusters offer for `gpu_id`, ascending.

    [] means the type is not offered for clusters at all; None means the
    catalog could not be read, so the caller should not conclude anything.
    """
    catalog = cluster_catalog()
    if catalog is None:
        return None
    for gpu in catalog:
        if gpu.gpu_id == gpu_id:
            return list(gpu.sizes)
    return []


def pick_gpus_per_node(requested: int, offered: list[int]) -> Optional[int]:
    """The node size to ask for: `requested` when the type offers it, the
    smallest offered size when nothing was requested, else None."""
    if not offered:
        return None
    if requested:
        return requested if requested in offered else None
    return offered[0]


# ---------------------------------------------------------------------------
# Create / inspect
# ---------------------------------------------------------------------------

_CREATE_CLUSTER = """
mutation CreateCluster($input: CreateClusterInput!) {
  createCluster(input: $input) {
    id
    name
    pods { id clusterIdx clusterIp }
  }
}
"""

_CLUSTER = """
query Cluster($id: String!) {
  myself {
    cluster(input: {id: $id}) {
      id
      pods { id clusterIdx clusterIp }
    }
  }
}
"""


_NODE_PRICE = """
query ClusterNodePrice($id: String!, $gpus: Int!) {
  gpuTypes(input: {id: $id}) {
    clusterPrice
    lowestPrice(input: {gpuCount: $gpus, isCluster: true, secureCloud: true}) {
      uninterruptablePrice
    }
  }
}
"""


def node_price(gpu_id: str, gpus_per_node: int) -> Optional[float]:
    """Hourly price of one cluster node. createCluster's `deployCost` is
    this times the node count: the API divides it by `podCount` and rejects
    the result if it is below the per-node minimum ("The requested price
    0.74 is less than the current minimum price (1.48)"). Omitting it reads
    as a price of 0.

    The live `lowestPrice` is what that check compares against; when the
    API has none (no live pool price, seen on dev for L4) the static
    per-GPU `clusterPrice` is the fallback. None if neither is known.
    """
    if config.CLUSTER_DEPLOY_COST > 0:
        return config.CLUSTER_DEPLOY_COST
    status, data = api.graphql(
        _NODE_PRICE, {"id": gpu_id, "gpus": gpus_per_node}, timeout=30,
    )
    if not (200 <= status < 300) or not isinstance(data, dict):
        api.log_error("cluster node price", status, data, indent=2)
        return None
    types = data.get("gpuTypes") or []
    entry = types[0] if types and isinstance(types[0], dict) else {}
    live = (entry.get("lowestPrice") or {}).get("uninterruptablePrice")
    if isinstance(live, (int, float)) and live > 0:
        return float(live)
    static = entry.get("clusterPrice")
    if isinstance(static, (int, float)) and static > 0:
        return round(float(static) * gpus_per_node, 4)
    return None


def cluster_ports() -> str:
    """SSH, Jupyter and Grafana on every node. Only the head serves Grafana,
    but a cluster has one template for all its pods."""
    return f"8888/http,{config.GRAFANA_PORT}/http,22/tcp"


def create_cluster_input(
    image: str,
    gpu_id: str,
    name: str,
    *,
    node_count: int,
    gpus_per_node: int,
    group: Optional[str] = None,
    deploy_cost: Optional[float] = None,
) -> dict:
    """The `CreateClusterInput` for one smoke attempt. Split out so it can
    be asserted on without an API."""
    env = [
        # start.sh only launches Jupyter with a password, and the Grafana
        # auth proxy reuses the same secret as its token.
        {"key": "JUPYTER_PASSWORD", "value": config.JUPYTER_TEST_PASSWORD},
        # post_start.sh builds Grafana's root_url and CSRF-trusted origin
        # from this; without it a dev cluster would trust the prod domain.
        {"key": "RUNPOD_PROXY_BASE", "value": config.PROXY_DOMAIN},
    ]
    body: dict = {
        "clusterName": name,
        "gpuTypeId": gpu_id,
        "podCount": node_count,
        "gpuCountPerPod": gpus_per_node,
        "type": "TRAINING",
        "imageName": image,
        "containerDiskInGb": config.DISK_GB,
        "volumeInGb": 0,
        "ports": cluster_ports(),
        "startSsh": True,
        "env": env,
    }
    cuda = (config.GROUP_MIN_CUDA.get(group) if group else None) or (
        detect_cuda_version(image)
    )
    if cuda:
        body["minCudaVersion"] = cuda
    if deploy_cost:
        body["deployCost"] = deploy_cost
    if config.REGISTRY_AUTH_ID:
        body["containerRegistryAuthId"] = config.REGISTRY_AUTH_ID
    dcs = [d.strip() for d in config.CLUSTER_DATA_CENTER_IDS.split(",") if d.strip()]
    if dcs:
        body["dataCenterIds"] = dcs
    return body


def create_cluster(
    image: str,
    gpu_id: str,
    name: str,
    *,
    node_count: int,
    gpus_per_node: int,
    group: Optional[str] = None,
) -> tuple[Optional[str], str, str]:
    """Create a cluster. Same `(id, kind, detail)` contract as
    pod.create_pod: kind is '' on success, else UNAVAILABLE / TRANSIENT /
    FATAL."""
    per_node = node_price(gpu_id, gpus_per_node)
    deploy_cost = None
    if per_node is None:
        log("node price unknown — createCluster will likely reject the request", indent=2)
    else:
        deploy_cost = round(per_node * node_count, 4)
        log(
            f"deployCost: ${deploy_cost}/hr (${per_node}/hr x {node_count} nodes)",
            indent=2,
        )
    body = create_cluster_input(
        image, gpu_id, name, node_count=node_count,
        gpus_per_node=gpus_per_node, group=group, deploy_cost=deploy_cost,
    )
    status, data = api.graphql(_CREATE_CLUSTER, {"input": body}, timeout=180)
    if 200 <= status < 300 and isinstance(data, dict):
        cluster = data.get("createCluster") or {}
        cluster_id = cluster.get("id")
        if cluster_id:
            return str(cluster_id), "", ""
        return None, "FATAL", "createCluster returned no id"
    return None, api.classify_error(status, data), api.error_detail(status, data)


def parse_cluster_nodes(pods: object) -> list[ClusterNode]:
    """Member pods sorted by rank. Pods without an id or a rank yet are
    left out — they are still being placed."""
    nodes: list[ClusterNode] = []
    for pod in pods if isinstance(pods, list) else []:
        if not isinstance(pod, dict) or not pod.get("id"):
            continue
        idx = pod.get("clusterIdx")
        if not isinstance(idx, int):
            continue
        nodes.append(ClusterNode(str(pod["id"]), idx, str(pod.get("clusterIp") or "")))
    return sorted(nodes, key=lambda n: n.idx)


def cluster_nodes(cluster_id: str) -> Optional[list[ClusterNode]]:
    """Current member pods, or None when the lookup failed or the cluster
    no longer exists."""
    status, data = api.graphql(_CLUSTER, {"id": cluster_id}, timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        return None
    cluster = (data.get("myself") or {}).get("cluster")
    if not isinstance(cluster, dict):
        return None
    return parse_cluster_nodes(cluster.get("pods"))


def wait_for_nodes(
    cluster_id: str, node_count: int,
) -> tuple[Optional[list[ClusterNode]], str]:
    """Poll until all `node_count` members exist and exactly one is the
    head. Returns (nodes, "") or (None, reason)."""
    deadline = time.time() + config.CLUSTER_PODS_TIMEOUT
    last: Optional[list[ClusterNode]] = None
    while time.time() < deadline:
        nodes = cluster_nodes(cluster_id)
        if nodes is not None:
            last = nodes
            if len(nodes) >= node_count:
                heads = [n for n in nodes if n.is_head]
                if len(heads) != 1:
                    return None, (
                        f"cluster has {len(heads)} pods with clusterIdx 0 "
                        f"(ranks: {[n.idx for n in nodes]})"
                    )
                return nodes, ""
        time.sleep(config.POLL_INTERVAL)
    seen = len(last) if last is not None else "no"
    return None, (
        f"only {seen} of {node_count} member pods appeared within "
        f"{config.CLUSTER_PODS_TIMEOUT}s"
    )
