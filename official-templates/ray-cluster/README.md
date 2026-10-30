# Ray cluster (`runpod/ray-cluster`)

Runpod's supported Ray cluster image for Instant Clusters. It layers Ray on `runpod/pytorch-cluster`, so it inherits the RDMA/InfiniBand user-space stack and the monitoring stack (DCGM + node_exporter on every node; Prometheus + Grafana on the head), and adds a Ray head/worker launch with Ray's metrics wired into that stack.

Published as `runpod/ray-cluster:<version>-cu<cuda>-torch<torch>-<ubuntu>`. Design: [Ray Clusters for Inference (v2: Supported Ray Image)](https://app.notion.com/p/runpod/Ray-Clusters-for-Inference-v2-Supported-Ray-Image-3f4ff732fc34813daebccb35ab5d4712); host side in runpod/host `docs/ray-init-refactor.md`.

## Contract v1 with the host

Ray cluster pods run only on this image or one built `FROM` it. The host daemon (runpod/host) validates that the pod is on a designated image, injects topology env, and observes Ray from outside the container. It injects no script and reads nothing from the pod, so the image owns everything else. The image carries the label `com.runpod.ray-cluster.contract=v1`, which derived images inherit.

| Concern | Owner | Mechanism |
|---|---|---|
| Ray, Python, CUDA, torch versions | Image | Pinned at build time; head and workers share one image |
| Launch (`ray start --head` / `--address`) | Image | `ENTRYPOINT` `/opt/runpod/ray/entrypoint`, then `exec` into the CMD |
| Static defaults (`RAY_GCS_PORT=6379`, `RAY_USAGE_STATS_ENABLED=0`, `NCCL_SOCKET_FAMILY=AF_INET`, `NCCL_DEBUG=WARN`, `NCCL_NET_GDR_LEVEL=PHB`) | Image | Dockerfile `ENV` |
| Topology the image depends on: `NODE_RANK`, `NUM_NODES`, cluster membership in `/etc/hosts` (`node-0` … `node-N`) | Host | `buildClusterEnv` for the env; the host keeps `/etc/hosts` current while the pod runs, appending members as they start |
| Topology passed through, not used by the image (`PRIMARY_ADDR`, `MASTER_ADDR`, `NODE_ADDR`, `NODE_ROLE`, `WORLD_SIZE`, …) and NIC/RDMA (`NCCL_SOCKET_IFNAME`, `GLOO_SOCKET_IFNAME`, `NCCL_IB_*`) | Host | `buildClusterEnv`. The addresses are fixed at create, and unset when the head isn't running then, which is why the image uses `node-0` instead |
| Observability ports: dashboard 8265, metrics 20217 | Image | Fixed by contract `v1`; the entrypoint refuses overrides |
| Ray token authentication (dashboard API, GCS) | Image | The entrypoint sets `RAY_AUTH_MODE=token` with the cluster's shared secret; the host must send `Authorization: Bearer <token>` on the State API poll |
| Fabric NIC selection | Host | `NCCL_SOCKET_IFNAME` pinned from ground truth; no in-container self-heal |
| Readiness, liveness, Runpod metrics | Host | `pkg/rayready` polls the head dashboard; `pkg/raymetrics` scrapes every node's metrics port |
| Customer metrics (Grafana, dashboard Metrics tab) | Image | Prometheus + Grafana on the head |

## What the entrypoint does

`/opt/runpod/ray/entrypoint` is the only Ray launch logic. In order:

1. **Enforces the contract ports.** If `RAY_METRICS_PORT` or `RAY_DASHBOARD_PORT` is set to anything other than 20217 / 8265, or `RAY_START_EXTRA_ARGS` contains `--metrics-export-port` or `--dashboard-port`, it prints an error naming the variable and exits non-zero before starting Ray.
   **Turns on Ray's token authentication** (`RAY_AUTH_MODE=token`). The token is `RAY_AUTH_TOKEN` (or `RAY_AUTH_TOKEN_PATH`) if you set one, else `RAY_DASHBOARD_PASSWORD`, else `JUPYTER_PASSWORD`, exported as `RAY_AUTH_TOKEN` so the CMD, Jupyter and SSH sessions inherit it. Every node must resolve the same token, or workers can't join. With no secret at all it exits non-zero rather than run an open dashboard; `RAY_AUTH_MODE=disabled` is the explicit opt-out. Any other `RAY_AUTH_MODE` is refused (matched case-insensitively), as is a `RAY_AUTH_TOKEN_PATH` that isn't a non-empty file.
2. Takes its role from `NODE_RANK` (rank 0 is the head) and its own address from its `node-<NODE_RANK>` entry in `/etc/hosts`, for `--node-ip-address`. If that entry is missing it exits with an error rather than guess.
3. On a worker, waits with no deadline for the head GCS at `node-0`, re-reading `/etc/hosts` on every attempt and logging once a minute. While the head is stopped `node-0` is absent; the host adds it back once the head runs again, and the worker then joins without being recreated. Until then the host reports that rank as not alive.
4. Runs `ray start` with `--node-ip-address`, `--metrics-export-port=20217`, plus `--dashboard-host=0.0.0.0 --dashboard-port=8265` on the head, then `$RAY_START_EXTRA_ARGS` for tuning such as `--resources` or `--object-store-memory`. It then waits for the ports to be listening, because a port Ray can't bind kills its agent after `ray start` has returned. A failure here exits non-zero instead of letting Ray move to a port the host can't find.
5. On a worker, keeps it in the cluster: a background loop checks every 10s that the raylet is running and, once it isn't (the head restarted, or the raylet died), runs `ray stop --force`, waits for the head the same way as step 3, and joins again. A restarted head is a new cluster, so this restores the node but not the jobs, actors or Serve apps that were running; resubmit those. It also means `ray stop` on a worker is undone within seconds: stop the pod to take a worker out.
6. `exec "$@"` into the CMD (`/start.sh` by default: SSH, Jupyter, and the monitoring bringup in `/post_start.sh`). On a worker, `JUPYTER_PASSWORD` and `JUPYTER_DISABLE_AUTH` are cleared first, so Jupyter runs on the head only; map 8888 on the head. Any node can still `ray.init()` into the cluster.

It does not install packages, write readiness markers, or probe the fabric. A pod with no `NODE_RANK` (not a cluster pod) skips straight to the CMD without Ray. The head's Ray is not restarted if it crashes while its container keeps running; the host reports the cluster down until the pod is restarted.

It also logs a warning if the installed Ray differs from the version the image was built with (`RAY_CLUSTER_RAY_VERSION`), since the host's parsers are pinned to that version.

## Using the image

- **As is:** SSH or Jupyter into the head, then `ray job submit` or a Python driver. Per-job dependencies come from Ray's `runtime_env` or a venv on a network volume.
- **Override the CMD in the template** (for example a Ray Serve app on a network volume). The entrypoint still starts Ray first. Don't override the template's entrypoint: that skips Ray entirely.
- **Build `FROM runpod/ray-cluster:<tag>`** only for heavy or compiled dependencies or a locked-down production image. Keep the `ENTRYPOINT`, the Ray version, and ports 8265 and 20217.

## Ports

| Port | Service | Who reaches it |
|---|---|---|
| 6379 | Ray GCS | workers → head, to register |
| 8265 | Ray dashboard (head, bound `0.0.0.0`), token-authenticated | host readiness/liveness poll (`/api/gcs_healthz`, the State API's `/api/v0/nodes`); cluster owner's browser, map this in the Runpod template |
| 20217 | Ray metrics (every node) | host scrape; the head's Prometheus |
| 52365 | Ray dashboard agent (every node) | the head's dashboard, for jobs and logs |
| 8889 | Grafana, token-authenticated (inherited from `pytorch-cluster`) | cluster owner's browser; map this in the Runpod template |

All except Grafana and the dashboard are host-internal: the daemon reaches them on the docker bridge and leaves them unmapped. Unauthenticated, the Ray dashboard's API is job submission, which is remote code execution in the cluster (ShadowRay, CVE-2023-48022). Ray's own token authentication closes that, so 8265 is safe to map: the UI asks for the token once and keeps it in an HttpOnly `ray-authentication-token` cookie; API clients send `Authorization: Bearer <token>`. Health checks (`/api/gcs_healthz`), the static UI and the login endpoint stay public. The metrics port (20217) and the agent port (52365) are not gated, so keep them unmapped. **With `RAY_AUTH_MODE=disabled`, never map 8265.**

## Metrics for the cluster owner

On the head, `/post_start.sh` adds a Prometheus `ray` job that discovers every node through the service-discovery file Ray maintains (`/tmp/ray/prom_metrics_service_discovery.json`), so new or rejoined nodes are picked up without config changes. Grafana loads Ray's stock dashboards, which `ray start --head` generates for the installed Ray version, in a **Ray** folder alongside the inherited GPU/system dashboards and the Runpod Ray overview (`06-ray-cluster.json`). The entrypoint sets `RAY_PROMETHEUS_HOST`, `RAY_GRAFANA_HOST` and `RAY_GRAFANA_IFRAME_HOST` so the dashboard's Metrics tab embeds those panels. Prometheus retention is capped at 7 days and 10 GB. Set `RAY_CLUSTER_METRICS=0` to turn the head's Prometheus + Grafana off if you bring your own stack; your own Prometheus can scrape each node on 20217.

This data stays in the cluster. Runpod's copy is the host's own scrape (`host_ray_node_*`), which is internal only.

## Build and test

```bash
./bake.sh ray-cluster            # all targets
./bake.sh ray-cluster cu1300     # one CUDA-major shard
official-templates/ray-cluster/tests/contract.sh runpod/ray-cluster:<tag>
```

Each matrix entry builds `FROM` a published `runpod/pytorch-cluster:<CLUSTER_BASE_VERSION>-…` tag (see `docker-bake.hcl`), so that image must exist first. In CI, `build-ray-cluster` (in `.github/workflows/base.yml`) runs after `build-pytorch-cluster`. `ray-cluster` is its own release family (`ray-cluster-vX.Y.Z` tags, see `.github/families.yml`), so its version need not match the cluster image it builds on.

`tests/contract.sh` is CPU-only and needs no Runpod credentials. It runs the image under plain Docker with fixture topology env and checks:

- the contract label and `ENTRYPOINT`;
- that the inherited monitoring bringup picks the head by `NODE_RANK=0`, not by the `node-0` hostname (so Prometheus/Grafana and the Ray scrape job land on the same node; pytorch-cluster releases after 1.4.1 have this check);
- a table of boot refusals, each reporting its error before Ray starts: port overrides; a `RAY_GCS_PORT` or `NODE_RANK` out of range, not a number, overflowing or carrying a shell command; no auth secret; a `RAY_AUTH_MODE` other than `token`/`disabled`; a missing or empty `RAY_AUTH_TOKEN_PATH`;
- a table of accepted boots, checked from what they log: port bounds, leading zeros dropped, the auth mode matched case-insensitively, and the token precedence (`RAY_AUTH_TOKEN`, then `RAY_DASHBOARD_PASSWORD`, then `JUPYTER_PASSWORD`, or `RAY_AUTH_TOKEN_PATH`);
- that `RAY_AUTH_MODE=disabled` boots with auth off;
- that a pod without `NODE_RANK` boots without Ray;
- that a 2-node cluster forms from only `NODE_RANK`, `NUM_NODES` and `/etc/hosts`, with the worker started first, before `node-0` is in its `/etc/hosts`: the worker waits without starting Ray, then joins once `node-0` is added. Then head health (`/api/gcs_healthz`), both nodes `ALIVE` at their addresses in the State API (`/api/v0/nodes`, the query the host makes), metrics on 20217 from both nodes, and the worker's CMD running without the Jupyter env;
- that after the head restarts, the worker (left running) rejoins the new head by itself;
- that the dashboard API answers 401 with no token, 403 with a wrong one, and 200 with the bearer token or the cookie `/api/authenticate` sets. The head takes its token from `RAY_DASHBOARD_PASSWORD` and the worker from `JUPYTER_PASSWORD`, so the worker joining proves both resolve to the same cluster token.

CI runs it before pushing, and uploads the head's node-list and `/metrics` payloads (`RAY_CONTRACT_FIXTURE_DIR`) as the fixtures runpod/host pins in its parser tests.

## Keeping in sync with the host

On a Ray version bump, verify these together with runpod/host:

- **The node-list payload shape.** `pkg/rayready` parses the State API's `/api/v0/nodes` (`node_ip`, `state`, `num_filtered`), not the dashboard's `/nodes?view=summary`, which is a cache that can trail the GCS. A Ray relabel would make every node read DEAD and hold the cluster never-ready. Refresh the host fixtures from the contract-test artifact.
- **Token authentication.** `pkg/rayready`'s State API poll needs the cluster token as a bearer header; `/api/gcs_healthz` and the metrics port stay public. Ray versions that move these public paths change what the host can reach without the token.
- **The contract ports.** Changing 8265 or 20217 is a contract version bump: a new label value and a matching host release.
