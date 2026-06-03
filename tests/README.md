# Smoke tests for RunPod container images

Spins up each image on RunPod, waits for the pod to stay healthy for
`DWELL_SEC` seconds, optionally validates CUDA / Jupyter, then terminates.

```
./test_images.py [path/to/images.yaml] [group_filter]
```

Requirements:
- `runpodctl` (logged in)
- Python ≥ 3.9

The code is split into a small package next to the entry point:

```
tests/
├── README.md               ← you are here
├── test_images.py          ← entry point: main() + summary + CLI
└── runpod_smoke/
    ├── config.py           ← env vars, sentinels, shared mutable state
    ├── log.py              ← thread-tagged logging
    ├── manifest.py         ← parser + value normalizers
    ├── runpodctl.py        ← subprocess wrappers around the `runpodctl` binary
    ├── instances.py        ← GPU catalog, budget resolution, exclude filter, CUDA detection
    ├── pod.py              ← pod create/lifecycle/signals, registry auth
    ├── checks.py           ← SSH probe, CUDA functional check, Jupyter probes, log dumper
    └── runner.py           ← test_pair / test_image (per-image orchestration)
```

## Manifest schema

```yaml
groupname:
    images:                # list of docker images to test (required)
    - imagename
    instances:             # explicit list of GPU display names, priority order
    - "RTX A4000"
    max_price_per_hour: 1.0   # OR budget filter — auto-pick cheapest first
    min_vram_gb: 16           # extra filter for budget mode
    manufacturer: Nvidia      # 'Nvidia' or 'AMD' filter for budget mode
    exclude_instances:        # subtract fnmatch patterns from candidates
    - "*Blackwell*"
    min_cuda_version: "13.0"  # 'X.Y' string for --min-cuda-version (fallback only)
    test_jupyter: true        # opt-in JupyterLab in-pod + proxy check
```

Field reference:

| field | description |
|---|---|
| `images` | Docker images to test. **Required.** |
| `instances` | Explicit list of GPU display names, tried in order. One of `instances:` or `max_price_per_hour:` is required (except for `base_cpu`). |
| `max_price_per_hour` | USD/hr budget — auto-pick any GPU at this price or below, cheapest first. Loses to explicit `instances:` if both are set. |
| `min_vram_gb` | Extra filter for budget mode (default 0). |
| `manufacturer` | `Nvidia` or `AMD` filter for budget mode (default: any). |
| `exclude_instances` | fnmatch-style patterns (case-insensitive) subtracted from the candidate list AFTER `instances:` or budget selection. Useful for blocking known-bad host pairings without rewriting the whole list — e.g. `"*Blackwell*"` skips every Blackwell GPU (sm\_100 / sm\_120 are not in the kernel set of PyTorch ≤ 2.6 wheels). |
| `min_cuda_version` | `X.Y` string passed to `runpodctl pod create --min-cuda-version`. Only used as a **fallback** when the image tag itself doesn't encode a CUDA version (e.g. NGC `nvidia-pytorch:25.11`). Image tags like `cu1281` / `cuda1281` always win. |
| `test_jupyter` | `true` / `false` — when true, the pod is created with `JUPYTER_PASSWORD=admin` in env and HTTP port 8888 exposed, then the script SSHes in and verifies JupyterLab is actually listening. Use for groups whose images use `container-template/start.sh` (`runpod/base`, `runpod/pytorch`, `runpod/autoresearch`, `rocm`). Skip for NGC `nvidia-pytorch` (different entrypoint). Default: `false`. |

The `base_cpu` group is special: `runpodctl` 2.3.0 does not let us pick a
specific CPU flavor (`--gpu-id` is rejected for `--compute-type CPU`), so
the manifest needs ONLY an `images:` list for that group — no
`instances:` / `max_price_per_hour:` / `min_vram_gb:`. RunPod picks a CPU
flavor for us.

## Environment variables

| var | default | description |
|---|---|---|
| `CLOUD_TYPE` | `SECURE` | `SECURE` or `COMMUNITY`. |
| `DISK_GB` | `100` | Container disk size for GPU pods. |
| `CPU_DISK_GB` | `20` | Container disk size for CPU pods. RunPod caps this per CPU flavor (20 GB on the cheapest, 30 GB on larger ones); 20 is the universal safe value. |
| `RUNPOD_API_KEY` | _(from `~/.runpod/config.toml`)_ | Used for the GraphQL GPU pricing query. Set this in CI / containers without a config file. |
| `DWELL_SEC` | `60` | Extra seconds to wait after SSH becomes reachable, then re-probe SSH to catch containers that boot, accept SSH, then crash. Set 0 to skip the re-probe. |
| `CREATE_TIMEOUT` | `600` | Max seconds to wait for SSH to become reachable. |
| `POLL_INTERVAL` | `10` | Poll cadence for SSH probes. |
| `MAX_PARALLEL` | `1` | How many images to smoke-test concurrently. Each worker holds at most one pod, so this caps simultaneous live pods. Keep modest to avoid RunPod rate limits and surprise bills. |
| `CREATE_RETRIES` | `3` | Retry pod-create up to N times on transient RunPod 5xx errors (`Something went wrong`, 502/503). Capacity shortages are NOT retried. |
| `CREATE_RETRY_BACKOFF` | `10` | Seconds between retries (linear backoff). |
| `STALL_HINT_AFTER` | `180` | Seconds without an SSH endpoint before the script prints a hint about slow pulls / possible Docker Hub rate limit. |
| `SSH_LOG_FETCH` | `1` | `1`/`0` — fetch container logs via direct SSH at PASS/FAIL. |
| `RUNPOD_SSH_KEY` | _(empty)_ | Path to private key matching the `PUBLIC_KEY` `runpodctl` injects into pods. Auto-discovered from common locations if not set. |
| `JUPYTER_WAIT_TIMEOUT` | `30` | Seconds the in-pod Jupyter probe waits for `:8888` to bind. |
| `JUPYTER_PROXY_TIMEOUT` | `60` | Seconds the proxy probe retries while RunPod's ingress registers the new pod. |

## Functional check

Runs over SSH after the container is reachable. **The check is selected
by inspecting the image REF, not the manifest group name** — so new
groups don't silently skip the check:

- image has `pytorch` / `torch\d` in ref
  → `torch.cuda.is_available` + matmul on device (catches broken drivers,
  missing libs, mismatched toolkit/driver versions).
- image has `cuda` / `cu\d` / `rocm` (but no torch markers)
  → `nvidia-smi -L` + driver/memory query + `nvcc --version`. Covers base
  GPU images and `autoresearch` (whose torch is in a venv not reachable
  from the system Python we SSH into).
- otherwise (no GPU markers)
  → no check. Pod must still boot and survive `DWELL_SEC`.

## Jupyter check (opt-in via manifest `test_jupyter: true`)

Two stages, both must pass:

1. **In-pod.** SSH into the pod and `curl http://127.0.0.1:8888/api/status`
   with our token. Catches silent `start.sh` failures (e.g. `python3 -m
   jupyter` not finding the module on Ubuntu 22.04 — the kind of bug that
   prints `Jupyter Lab started` in the container log while no server is
   actually running).
2. **Public proxy.** From the test machine, `GET
   https://<pod-id>-8888.proxy.runpod.net/api/status` with the token.
   Catches port-type misconfigurations (`8888/tcp` instead of `8888/http`
   — the proxy never wires up non-http ports) and DNS / proxy
   registration issues that would prevent real users from reaching
   Jupyter from the RunPod console.

## Exit code

`0` if no `FAIL`, `1` otherwise. `SKIP` (no capacity / all instances
stuck) does not fail the run.
