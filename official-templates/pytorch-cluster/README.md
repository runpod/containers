# pytorch-cluster

A `-cluster` variant of the Runpod PyTorch image for **multi-node GPU clusters**.
It layers two things on top of `runpod/pytorch`:

1. **RDMA / InfiniBand user-space stack** — `libibverbs1`, `ibverbs-providers`,
   `rdma-core`, `ibverbs-utils`, `infiniband-diags`, `perftest`.
2. **A self-contained monitoring stack**, managed by `supervisord`:
   - **node_exporter** (`:9100`) and **dcgm-exporter** (`:9400`) run on **every** node.
   - **Prometheus** (`127.0.0.1:9090`) and **Grafana** (public `:8889` via the auth proxy) run **only on `node-0`**.
3. **Log aggregation**, also managed by `supervisord`:
   - **Grafana Alloy** (per-node log shipper) runs on **every** node and tails the
     Slurm logs, pushing them to the head node.
   - **Loki** (`0.0.0.0:3100`) runs **only on `node-0`** and stores the logs;
     Grafana queries it over loopback.
4. **Slurm job accounting backend** — **MariaDB** (`127.0.0.1:3306`) runs **only
   on `node-0`** with an empty `slurm_acct_db` database ready for `slurmdbd`.

Image tags follow the pytorch scheme with a `-cluster` suffix, e.g.
`runpod/pytorch:<version>-cu1281-torch280-ubuntu2404-cluster`.

## How it works at startup

The image reuses the shared `/start.sh`, which invokes the `/post_start.sh` hook
shipped here. On start, `post_start.sh`:

1. If `hostname` is **`node-0`**, renders `/etc/prometheus/prometheus.yml` with a
   `node` (`:9100`) and `dcgm` (`:9400`) scrape target for **every peer found in
   `/etc/hosts` whose name starts with `node-`** (falls back to localhost).
2. Starts `supervisord`, which brings up the exporters **and the Alloy log
   shipper** on every node.
3. If `hostname` is `node-0`, starts Loki + Prometheus + Grafana via `supervisorctl`.

Grafana is pre-provisioned with a Prometheus datasource pointing at
`http://127.0.0.1:9090` and a Loki datasource pointing at `http://127.0.0.1:3100`,
so the query traffic never leaves the head node.

## Log aggregation (Slurm)

Slurm itself is provisioned at **runtime** by Runpod (the image only bakes in the
`slurm-wlm` package); its logs land in the distro-standard `/var/log/slurm/`.
**Grafana Alloy** runs on every node (`autostart=true`, like the exporters),
tails `/var/log/slurm/*.log`, and pushes each line to the head-node **Loki** at
`http://node-0:3100`. Loki binds `0.0.0.0:3100` so compute-node shippers can
reach it; it stays on the private cluster network (only Grafana `:8889` is
public). Logs are queryable in the **Slurm Logs** dashboard or Grafana's Explore
view via the **Loki** datasource.

Alloy parses each line (`config/alloy/config.alloy`) before shipping, so logs
arrive with useful, low-cardinality **labels** — and the entry is re-stamped with
the log's own event time:

| Field | Kind | Values |
| --- | --- | --- |
| `node` | label | container hostname (`node-0`, `node-1`, …) |
| `component` | label | `slurmctld` / `slurmd` / `slurmdbd` (from the filename) |
| `level` | label | `info` / `verbose` / `debug` / `warning` / `error` / `fatal` |
| `job_id` | structured metadata | Slurm `JobId=<n>` (kept off the label set to avoid high cardinality) |

- Override the tailed path with the **`SLURM_LOG_GLOB`** env var (default
  `/var/log/slurm/*.log`).
- Alloy on compute nodes retries with backoff until `node-0`'s Loki is up, so
  startup order doesn't matter.
- Slurm writes local time without an offset; the images run **UTC**, so the
  timestamp is parsed as UTC. On parse failure the ingestion time is kept.
- **Note:** Alloy replaces Promtail, which Grafana declared end-of-life and
  dropped from Loki releases after the 3.5.x line.

## Slurm job accounting (MariaDB)

Slurm's accounting backend (`slurmdbd`) needs a MySQL/MariaDB database.
**MariaDB** (server + client) is installed in the image and runs **only on
`node-0`** (`autostart=false`; started by `post_start.sh`). It binds loopback
`127.0.0.1:3306`, so the accounting DB never leaves the head node.

On `node-0`, `post_start.sh` (idempotently, every boot):

1. Initialises the MariaDB data directory at
   **`/workspace/slurm-acct-db/$RUNPOD_POD_ID`** on first boot — on the RunPod
   persistent volume, scoped by node-0's pod id (see the note below).
2. Starts `mariadbd`.
3. Ensures the accounting database and login user exist:
   - database **`slurm_acct_db`**
   - user **`slurm`@`localhost`** with `GRANT ALL` on that database

> **Why the pod-id subdirectory?** RunPod exposes no stable per-cluster id, and
> two clusters can be attached to the same `/workspace` network volume. Scoping
> the datadir by node-0's `RUNPOD_POD_ID` guarantees two clusters never point two
> `mariadbd` instances at one InnoDB datadir (which would corrupt it). The
> trade-off: the pod id changes when a cluster is recreated, so **accounting
> history does not carry across a recreation** — each cluster instance gets its
> own datadir. Stale per-instance directories accumulate on the volume and can be
> pruned by hand.

> **Run user.** `/workspace` is a network volume that usually forbids `chown`
> (root is squashed). `post_start.sh` tries to give the datadir to the `mysql`
> user and, if that fails, runs `mariadbd` **as root** so it matches the volume's
> ownership — the resolved `user=` is written into the runtime-rendered
> `zz-slurm-acct-datadir.cnf`. A partial datadir left by a failed init is cleared
> before re-initialising.

`slurmdbd` **creates and owns the accounting tables itself** on first connect —
there is no schema dump to load; this only prepares the empty database and a
user it can authenticate as. Point `slurmdbd.conf` at it:

```ini
StorageType   = accounting_storage/mysql
StorageHost   = localhost
StorageLoc    = slurm_acct_db
StorageUser   = slurm
StoragePass   = slurm
```

Overridable via env (set them **before** first boot; `StoragePass` in
`slurmdbd.conf` must match): `SLURM_ACCT_DB_NAME`, `SLURM_ACCT_DB_USER`,
`SLURM_ACCT_DB_PASSWORD` (all default as above). InnoDB tuning follows SchedMD's
recommendations (`config/mariadb/99-slurm-acct.cnf`).

> Slurm itself (`slurmctld` / `slurmd` / `slurmdbd` / `munge`) is provisioned at
> runtime by RunPod — the image only supplies the MariaDB backend.

## Pre-baked dashboards

Grafana auto-loads these dashboards (at the top level — no nested folder) from
`/var/lib/grafana/dashboards`. The branded **Runpod Cluster Home** is set as the
default landing page (replacing Grafana's welcome page):

- **Runpod Cluster Home** — branded landing: hero stats + quick links to the rest.
- **GPU Fleet Overview** — cluster-wide utilization, Tensor Core activity, power,
  memory, temperature and XID error count.
- **GPU Training Deep Dive** — per-node/per-GPU compute saturation (GPU / SM /
  Tensor), precision-pipe (FP16/32/64) and DRAM activity, framebuffer memory,
  clocks, PCIe/NVLink throughput, and XID/ECC/replay errors.
- **Node & System** — CPU, memory, disk I/O, network, filesystem, load (from
  node_exporter).
- **Fabric & Interconnect** — grouped by fabric: **InfiniBand / RoCE** (port &
  physical state now and over time, adapter inventory, link signal-rate
  capacity), **PCIe (DCGM)** (per-GPU link gen/width and replay rate),
  **Ethernet Fabric** (throughput, packet rate, errors/drops, carrier flaps),
  **TCP Health** (retransmits, established/in-use sockets), and **Clock Sync**
  (NTP offset, time-sync status).
- **Slurm Logs** — Slurm logs from every node (via Loki): error/warning stat
  tiles, log-volume timelines by level and by node, a dedicated errors &
  warnings stream, and the full log stream — all filterable by node, component,
  level, and a full-text search box.

The training signals (Tensor Core / DRAM / NVLink activity) come from DCGM
profiling (DCP) metrics, so dcgm-exporter runs with Runpod's extended counter
set at `/etc/dcgm-exporter/extended-counters.csv` (from the `runpod/ansible-host`
monitoring role) rather than the default. Note this set uses
`DCGM_FI_PROF_GR_ENGINE_ACTIVE` (compute-engine active ratio) as the utilization
signal instead of the coarse `DCGM_FI_DEV_GPU_UTIL`.

Inspect running services with `supervisorctl status`; logs live under
`/var/log/supervisor/`.

## Accessing Grafana

Grafana is reached on port `8889` (expose it on the `node-0` pod). The auth proxy
fronts Grafana there; Grafana itself binds loopback `:3300`. Auto-login is
handled by a tiny reverse proxy that mirrors Jupyter's shared-token model.

### Seamless auto-login — shared token (mirrors Jupyter)

Jupyter takes a shared secret from `$JUPYTER_PASSWORD` and the console opens
`…-8888.proxy.runpod.net/lab?token=<JUPYTER_PASSWORD>`. Grafana **reuses the same
`JUPYTER_PASSWORD` secret**:

- Grafana binds loopback `:3300` with `[auth.proxy]`; a tiny stdlib proxy
  (`config/grafana-proxy/auth_proxy.py`) listens on `:8889`.
- The proxy reads `?token=` (or its `cluster_auth` cookie), constant-time
  compares it to `JUPYTER_PASSWORD`, and on match proxies to Grafana injecting
  `X-WEBAUTH-User` + setting an HttpOnly cookie so the browser SPA stays logged
  in. No/invalid token → no header → Grafana login form.
- Client-supplied `X-WEBAUTH-*` is stripped (unspoofable), and Grafana is
  loopback-only so nothing bypasses the proxy.

Setup (nothing new — same secret as Jupyter):
1. The pod already has **`JUPYTER_PASSWORD`** (the Jupyter secret). Omit it → no
   auto-login, Grafana shows its login form. Set `GRAFANA_PASSWORD` only if you
   want a Grafana-specific token instead.
2. The console opens `https://<pod>-8889.<proxy-base>/?token=<JUPYTER_PASSWORD>`.

Notes:
- **Dev pods:** set `RUNPOD_PROXY_BASE=dev-proxy.runpod.net` so `post_start.sh`
  builds the correct `root_url` (defaults to `proxy.runpod.net`).
- The logged-in user is `GRAFANA_PROXY_USER` (default `runpod`, Admin via
  `auto_assign_org_role`).
- **No admin/admin login.** The username/password login form and HTTP basic auth
  are disabled, and the built-in admin account gets a random password at startup
  — the auth proxy is the only way in.

## Building locally

`-cluster` builds `FROM` a published `runpod/pytorch:*` tag, so that base image
must exist first (build it, or point `BASE_IMAGE` at a published tag). Then:

```bash
./bake.sh pytorch-cluster cu1281   # or another per-CUDA-major group
```
