# Ray cluster (`runpod/ray-cluster`)

Runpod's supported Ray cluster image for Instant Clusters. It layers Ray on the `runpod/pytorch` `-cluster` variant, so it inherits the RDMA/InfiniBand user-space stack and the monitoring stack (DCGM + node_exporter on every node; Prometheus + Grafana on the head), and adds a Ray head/worker launch with Ray's metrics wired into that stack.

Published as `runpod/ray-cluster:<version>-cu<cuda>-torch<torch>-<ubuntu>`. Design: [Ray Clusters for Inference (v2: Supported Ray Image)](https://app.notion.com/p/runpod/Ray-Clusters-for-Inference-v2-Supported-Ray-Image-3f4ff732fc34813daebccb35ab5d4712); host side in runpod/host `docs/ray-init-refactor.md`.

## Contract v1 with the host

Ray cluster pods run only on this image or one built `FROM` it. The host daemon (runpod/host) validates that the pod is on a designated image, injects topology env, and observes Ray from outside the container. It injects no script and reads nothing from the pod, so the image owns everything else. The image carries the label `com.runpod.ray-cluster.contract=v1`, which derived images inherit.

| Concern | Owner | Mechanism |
|---|---|---|
| Ray, Python, CUDA, torch versions | Image | Pinned at build time; head and workers share one image |
| Launch (`ray start --head` / `--address`) | Image | `ENTRYPOINT` `/opt/runpod/ray/entrypoint`, then `exec` into the CMD |
| Static defaults (`RAY_GCS_PORT=6379`, `RAY_USAGE_STATS_ENABLED=0`, `NCCL_SOCKET_FAMILY=AF_INET`, `NCCL_DEBUG=WARN`, `NCCL_NET_GDR_LEVEL=PHB`) | Image | Dockerfile `ENV` |
| Topology (`PRIMARY_ADDR`, `NODE_ADDR`, `NODE_RANK`, `NUM_NODES`, `NODE_ROLE`, `WORLD_SIZE`, `NCCL_SOCKET_IFNAME`, `GLOO_SOCKET_IFNAME`, RDMA `NCCL_IB_*`) | Host | `buildClusterEnv` |
| Observability ports: dashboard 8265, metrics 20217 | Image | Fixed by contract `v1`; the entrypoint refuses overrides |
| Fabric NIC selection | Host | `NCCL_SOCKET_IFNAME` pinned from ground truth; no in-container self-heal |
| Readiness, liveness, Runpod metrics | Host | `pkg/rayready` polls the head dashboard; `pkg/raymetrics` scrapes every node's metrics port |
| Customer metrics (Grafana, dashboard Metrics tab) | Image | Prometheus + Grafana on the head |

## What the entrypoint does

`/opt/runpod/ray/entrypoint` is the only Ray launch logic. In order:

1. **Enforces the contract ports.** If `RAY_METRICS_PORT` or `RAY_DASHBOARD_PORT` is set to anything other than 20217 / 8265, or `RAY_START_EXTRA_ARGS` contains `--metrics-export-port` or `--dashboard-port`, it prints an error naming the variable and exits non-zero before starting Ray.
2. Maps `NODE_ROLE` (`RAY_HEAD` / `RAY_WORKER`) to head or worker and strips the CIDR from `NODE_ADDR`.
3. On a worker, waits up to `RAY_HEAD_WAIT_SECONDS` (600) for the head GCS. If the head never answers it logs an error and runs the CMD without Ray, so the pod stays up for debugging and the host reports that rank as not alive.
4. Runs `ray start` with `--node-ip-address`, `--metrics-export-port=20217`, plus `--dashboard-host=0.0.0.0 --dashboard-port=8265` on the head, then `$RAY_START_EXTRA_ARGS` for tuning such as `--resources` or `--object-store-memory`. It then waits for the ports to be listening, because a port Ray can't bind kills its agent after `ray start` has returned. A failure here exits non-zero instead of letting Ray move to a port the host can't find.
5. `exec "$@"` into the CMD (`/start.sh` by default: SSH, Jupyter, and the monitoring bringup in `/post_start.sh`).

It does not install packages, write readiness markers, or probe the fabric. A pod with no `NODE_ROLE` (not a cluster pod) skips straight to the CMD without Ray. Ray is not restarted if it crashes after joining; the container stays up and the host sees the node go from alive to not alive.

It also logs a warning if the installed Ray differs from the version the image was built with (`RAY_CLUSTER_RAY_VERSION`), since the host's parsers are pinned to that version.

## Using the image

- **As is:** SSH or Jupyter into the head, then `ray job submit` or a Python driver. Per-job dependencies come from Ray's `runtime_env` or a venv on a network volume.
- **Override the CMD in the template** (for example a Ray Serve app on a network volume). The entrypoint still starts Ray first. Don't override the template's entrypoint: that skips Ray entirely.
- **Build `FROM runpod/ray-cluster:<tag>`** only for heavy or compiled dependencies or a locked-down production image. Keep the `ENTRYPOINT`, the Ray version, and ports 8265 and 20217.

## Ports

| Port | Service | Who reaches it |
|---|---|---|
| 6379 | Ray GCS | workers → head, to register |
| 8265 | Ray dashboard (head, bound `0.0.0.0`) | host readiness/liveness poll (`/nodes?view=summary`, `/api/gcs_healthz`) |
| 20217 | Ray metrics (every node) | host scrape; the head's Prometheus |
| 52365 | Ray dashboard agent | local `HEALTHCHECK` (`/api/healthz`) |
| 8889 | Grafana, token-authenticated (inherited from `-cluster`) | cluster owner's browser; map this in the Runpod template |

All except Grafana are host-internal: the daemon reaches them on the docker bridge and leaves them unmapped. **Do not map 8265 through the Runpod proxy.** The Ray dashboard is unauthenticated and allows job submission, which is remote code execution in the cluster (ShadowRay, CVE-2023-48022). An authenticated dashboard route is a launch blocker tracked separately.

## Metrics for the cluster owner

On the head, `/post_start.sh` adds a Prometheus `ray` job that discovers every node through the service-discovery file Ray maintains (`/tmp/ray/prom_metrics_service_discovery.json`), so new or rejoined nodes are picked up without config changes. Grafana loads Ray's stock dashboards, which `ray start --head` generates for the installed Ray version, in a **Ray** folder alongside the inherited GPU/system dashboards and the Runpod Ray overview (`06-ray-cluster.json`). The entrypoint sets `RAY_PROMETHEUS_HOST`, `RAY_GRAFANA_HOST` and `RAY_GRAFANA_IFRAME_HOST` so the dashboard's Metrics tab embeds those panels. Prometheus retention is capped at 7 days and 10 GB. Set `RAY_CLUSTER_METRICS=0` to turn the head's Prometheus + Grafana off if you bring your own stack; your own Prometheus can scrape each node on 20217.

This data stays in the cluster. Runpod's copy is the host's own scrape (`host_ray_node_*`), which is internal only.

## Diagnostics

- `/opt/runpod/ray/health`: the local probe behind the Docker `HEALTHCHECK`; exits 0 when this node's agent reports the raylet and GCS healthy.
- `/opt/runpod/ray/fabric-probe`: opt-in NCCL all-reduce across one GPU per node. Run it on the head once every node has joined. It prints one `RAYFABRIC ok=... gbps=... reason=...` line and always exits 0. It is not on the boot path.

## Build and test

```bash
./bake.sh ray-cluster            # all targets
./bake.sh ray-cluster cu1300     # one CUDA-major shard
official-templates/ray-cluster/tests/contract.sh runpod/ray-cluster:<tag>
```

Each matrix entry builds `FROM` a published `runpod/pytorch:<CLUSTER_BASE_VERSION>-…-cluster` tag (see `docker-bake.hcl`), so that image must exist first. In CI, `build-ray-cluster` (in `.github/workflows/base.yml`) runs after `build-cluster`.

`tests/contract.sh` is CPU-only and needs no Runpod credentials. It runs the image under plain Docker with fixture topology env and checks:

- the contract label and `ENTRYPOINT`;
- that each port override is refused;
- that a pod without `NODE_ROLE` boots without Ray;
- that a 2-node cluster forms: head health, both raylets `ALIVE` in `/nodes?view=summary`, metrics on 20217 from both nodes, and the `HEALTHCHECK` passing.

CI runs it before pushing, and uploads the head's `/nodes` and `/metrics` payloads (`RAY_CONTRACT_FIXTURE_DIR`) as the fixtures runpod/host pins in its parser tests.

## Keeping in sync with the host

On a Ray version bump, verify these together with runpod/host:

- **The dashboard payload shape.** `pkg/rayready` parses `/nodes?view=summary` (`ip`, `raylet.state`). A Ray relabel would make every node read DEAD and hold the cluster never-ready. Refresh the host fixtures from the contract-test artifact.
- **The contract ports.** Changing 8265 or 20217 is a contract version bump: a new label value and a matching host release.
