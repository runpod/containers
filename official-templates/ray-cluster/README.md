# Ray cluster (`-ray-cluster`)

A Ray head/worker cluster image for Runpod Instant Clusters. It layers Ray on top of the `runpod/pytorch` `-cluster` variant, so it inherits the full cluster feature set — the RDMA/InfiniBand user-space stack and the self-contained monitoring stack (DCGM + node_exporter on every node; Prometheus + Grafana on the head) — and adds a Ray head/worker that registers into a single cluster, with Ray's own metrics wired into that Prometheus/Grafana.

Published as `runpod/ray:<version>-cu<cuda>-torch<torch>-<ubuntu>`.

## How it fits the host

The host daemon (runpod/host) drives cluster pods by **injecting topology env and observing from outside the container** — it does not inject a launch script. This image owns launch. See `docs/ray-init-refactor.md` in runpod/host for the full design.

- **The image owns launch.** `/ray-entrypoint.sh` reads the injected env, runs the fabric preflight, and runs `ray start` (head or worker) under supervisord.
- **The host observes from outside.** The daemon polls this node's Ray dashboard for readiness/liveness (`pkg/rayready`) and scrapes its Ray metrics (`pkg/raymetrics`). Nothing in the container reports readiness to the host via a file or marker.

Because of that split, the ports below are a **contract with the host** — do not rename them without changing runpod/host.

## Environment contract (injected by the daemon)

`buildClusterEnv` (runpod/host `pkg/docker/container_create.go`) injects, per cluster pod:

| Var | Meaning |
|---|---|
| `NODE_ROLE` | `RAY_HEAD` / `RAY_WORKER` — selects head vs worker in the entrypoint |
| `NODE_ADDR` | this pod's own overlay IP (CIDR-suffixed); Ray's `--node-ip-address` |
| `PRIMARY_ADDR` | the head's overlay IP (node-0); workers register against it |
| `NUM_NODES` | expected cluster size (host uses it for the readiness verdict) |
| `NODE_RANK` | this node's rank in the cluster |
| `RUNPOD_GPU_COUNT` | GPUs on this node |
| `RAY_METRICS_PORT` | pinned Ray Prometheus metrics port (single source of truth with the host scraper) |
| `NCCL_*` / `GLOO_*` / IB vars | fabric hints, when the host is RDMA-capable; the preflight self-heals `NCCL_SOCKET_IFNAME` against ground truth |

Overridable knobs (defaults in parentheses): `RAY_GCS_PORT` (6379), `RAY_DASHBOARD_PORT` (8265), `RAY_METRICS_PORT` (8080), `RAY_DASHBOARD_AGENT_PORT` (52365), `RAY_HEAD_WAIT_SECONDS` (600), `RAY_NCCL_GDR_LEVEL` (PHB).

## Ports

| Port | Service | Who reaches it |
|---|---|---|
| 6379 | Ray GCS | workers → head, to register |
| 8265 | Ray dashboard (bound `0.0.0.0`) | host readiness/liveness poll (`/api/healthz`, `/nodes?view=summary`) |
| 8080 | Ray Prometheus metrics (`RAY_METRICS_PORT`) | host metrics scrape; local Prometheus |
| 52365 | Ray dashboard agent | per-node raylet healthz; local liveness probe / `HEALTHCHECK` |
| 8889 | Grafana (HTTP) | user browser (inherited from `-cluster`); map this in the Runpod template |

All except Grafana are host-internal — the daemon reaches them on the docker bridge and leaves them unmapped.

## Initialization, registration, readiness/liveness, metrics

- **Initialization** (`/ray-entrypoint.sh`): strip the CIDR from `NODE_ADDR`, source `/opt/ray-cluster/fabric.sh` to self-heal the NCCL fabric interface and fill NCCL/Gloo gaps, then pin the metrics port (with a collision fallback: if the port is taken, start without `--metrics-export-port` and log loudly rather than crash-loop).
- **Registration**: the head runs `ray start --head`; each worker waits (TCP) for the head GCS at `PRIMARY_ADDR:RAY_GCS_PORT`, then `ray start --address=...` joins it. Under supervisord (`ray-node`, `autorestart=true`), a worker whose head isn't up yet exits and is retried — that is the registration retry loop.
- **Readiness / liveness exposed to the host**: the head dashboard on `:8265` answers `/api/healthz` (head liveness) and `/nodes?view=summary` (formation + per-node ALIVE state) — the endpoints `pkg/rayready` polls. `/ray-health.sh {liveness,readiness}` is the in-container mirror (KubeRay-style `wget … | grep success`), driving the Docker `HEALTHCHECK`.
- **Metrics exposed to the host**: `ray start --metrics-export-port=$RAY_METRICS_PORT` exports per-node Ray Prometheus metrics; the host scrapes it, and on the head the bundled Prometheus also scrapes every `node-*:$RAY_METRICS_PORT` peer, surfaced in the "Runpod Ray Cluster" Grafana dashboard alongside the GPU/system dashboards.

## Build

```bash
./bake.sh ray-cluster            # all targets
./bake.sh ray-cluster cu1300     # one CUDA-major shard
```

`bake.sh` passes `official-templates/shared/versions.hcl`, which supplies `RELEASE_VERSION` / `RELEASE_SUFFIX`. Each matrix entry builds `FROM` a published `runpod/pytorch:<CLUSTER_BASE_VERSION>-…-cluster` tag (see `docker-bake.hcl`), so the corresponding `-cluster` image must exist first.

## Keeping in sync with the host

Two things drift silently if the host and image diverge — verify them together on a Ray version bump:

- **The dashboard payload shape.** `pkg/rayready` parses `/nodes?view=summary` (`ip`, `raylet.state`); a Ray relabel would make every node read DEAD and hold the cluster never-ready.
- **`config/fabric.sh`** is a copy of runpod/host `pkg/cluster/fabric.sh`. The Slurm arm still uses the host's copy; keep this one in step so both arms self-heal the fabric identically.
