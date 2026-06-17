# Smoke tests for RunPod container images

Spins up each image on a real RunPod pod, waits for it to stay healthy
for `DWELL_SEC` seconds, runs an image-appropriate functional check
(CUDA / `nvidia-smi` / `torch.cuda` / optional JupyterLab), then
terminates the pod. Designed to catch the failure modes that **only
appear on a real GPU host** and that local `docker run` would miss:
driver-version mismatches, broken NCCL/NVRTC, missing CUDA libs,
`start.sh` regressions, JupyterLab proxy misconfiguration, etc.

```
./test_images.py [path/to/images.yaml] [group_filter]
```

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


## Prerequisites

1. **Python ≥ 3.9** (stdlib only — no pip install needed).
2. **`runpodctl` 2.3.0+ on `$PATH`**, authenticated:

   ```bash
   runpodctl config --apiKey <YOUR_RUNPOD_API_KEY>
   runpodctl user   # smoke test — should print your account info
   ```

   The API key needs **pod-management** permissions. You can find /
   generate one at <https://www.runpod.io/console/user/settings>.

3. **SSH key registered on your RunPod account.** `test_images.py`
   probes every pod over SSH for the real readiness signal and the
   GPU/CUDA functional check. `runpodctl` writes a managed key pair on
   first use; if you already have one in `~/.runpod/ssh/` you're set.
   To use a different key, point `RUNPOD_SSH_KEY` at the private half
   AND make sure the matching public half is registered at
   <https://www.runpod.io/console/user/settings#ssh-keys>.

4. **(Recommended)** A Docker Hub registry auth registered with
   `runpodctl registry add`. RunPod datacenters share an anonymous Hub
   IP pool that hits the `toomanyrequests` rate limit fast — without
   auth, parallel runs in particular will produce a wave of
   "image pull backoff" failures that look like image bugs but aren't.
   The script auto-discovers the first entry from `runpodctl registry
   list`; pin a specific one with `REGISTRY_AUTH_ID` or
   `REGISTRY_AUTH_NAME`.


## Quick start

Smallest possible manifest — single CPU image:

```yaml
# images-quickstart.yaml
base_cpu:
    images:
    - runpod/base:1.0.6-dev-ubuntu2404
```

Run it:

```bash
./test_images.py images-quickstart.yaml
```

You should see, in order:

1. `discovered N GPU types from runpodctl` — startup catalog query
2. `using registry auth: …` — Docker Hub auth resolved (or a warning)
3. `==================== running 1 job(s) with MAX_PARALLEL=1 ===`
4. `attempt: CPU pod …` → `pod p-xxx created, waiting for RUNNING`
5. `t+Ns endpoint=root@…:NNNN ssh_probe=OK` — pod is up
6. `dwelling 60s and re-probing SSH...`
7. `--- pod metadata for p-xxx ---` + log dump
8. `Cleaning up pod p-xxx...`
9. `===== SUMMARY ===== totals: 1 PASS, 0 FAIL, 0 SKIP`

Exit code is `0` if no `FAIL` and no `SKIP`, `1` otherwise. `SKIP` is
treated as a failure by default because it means no real validation
happened; set `ON_SKIP=warn` (CI: `on-skip: 'warn'`) to keep the job
green with a yellow GitHub Actions warning annotation, or `ON_SKIP=pass`
for the legacy fully-lenient behaviour. See the [Outcomes](#outcomes)
table below.

To test a single group from a larger manifest:

```bash
./test_images.py images.yaml base_cpu
```


## Test lifecycle

For every `(image, instance)` pair the manifest produces, the script
runs this sequence and reports the outcome as soon as one step fails.

| # | Step | Failure → |
|---|------|---|
| 1 | `runpodctl pod create` (with `--gpu-id`, `--container-disk-in-gb`, `--ports`, registry auth, optional `--min-cuda-version`). Transient `5xx` / `Something went wrong` errors are retried silently up to `CREATE_RETRIES` with linear backoff. | `UNAVAILABLE` (no capacity for this instance type — try next) / `CREATE_FAIL` (bad image tag, registry auth, malformed request — any non-capacity, non-transient orchestrator error after retries are exhausted) |
| 2 | Poll `runpodctl pod get` until `ssh.ip` / `ssh.port` are assigned and one-shot `ssh root@ip -p port 'echo ready'` succeeds (the real readiness signal — `desiredStatus` is always `RUNNING` after create) | `STUCK` if no SSH endpoint within `CREATE_TIMEOUT` (almost always a bad host in the scheduler pool — try another instance type) |
| 3 | **CUDA functional check** over SSH — see [Functional check](#functional-check). Image-driven: pytorch ref → `torch.cuda` + matmul; cuda/rocm ref → `nvidia-smi` + `nvcc`; neither → skip | `FAIL` (image is broken — stop iterating; another GPU won't help) |
| 4 | **JupyterLab in-pod check** (only when `test_jupyter: true`) — see [Jupyter check](#jupyter-check-opt-in). SSH in, wait for `:8888` to bind, `jupyter server list`, `curl /api/status` with token | `FAIL` (`start.sh` didn't bring up Jupyter — usually wrong python interpreter) |
| 5 | **JupyterLab public-proxy check** (only when `test_jupyter: true`) — `GET https://<pod-id>-8888.proxy.runpod.net/api/status` from the test machine | `FAIL` (port not exposed as `8888/http`, or proxy never registered) |
| 6 | Sleep `DWELL_SEC`, re-probe SSH (catches "boots fine then crashes after 30s") | `FAIL` if SSH stops responding |
| 7 | `dump_pod_logs` — pull `uname`, `syslog`, `dmesg`, `/var/log/*.log`, `nvidia-smi` via SSH for the run log | _(diagnostic only)_ |
| 8 | `runpodctl pod delete` (always — even on Ctrl-C / exception via `atexit` + signal handlers) | _(diagnostic only)_ |

`test_image()` then iterates over the next instance candidate when the
result was `UNAVAILABLE` or `STUCK`, and short-circuits on `PASS`,
`FAIL`, or `CREATE_FAIL`.


## Outcomes

The summary at the end of every run groups results into three buckets.
The granular per-pod outcomes below collapse into them:

| summary | per-pod outcome | what it means | what to do |
|---|---|---|---|
| `PASS` | `PASS` | Image booted, all checks passed, survived dwell. | nothing |
| `FAIL` | `FAIL` | Pod was created and the container itself proved broken (CUDA check failed, JupyterLab didn't start, crashed during dwell, etc.). Moving to another GPU won't help — the image is the problem. | fix the image |
| `FAIL` | `CREATE_FAIL` | Pod-create returned a non-capacity, non-transient orchestrator error (bad image tag, registry auth, malformed request, missing CUDA version). | fix the manifest / image ref / auth |
| `SKIP` | all `UNAVAILABLE` | RunPod had no capacity on **any** candidate instance type. | retry later, expand `instances:` list, or raise `max_price_per_hour` |
| `SKIP` | some `STUCK` + rest `UNAVAILABLE` | At least one instance was scheduled but RunPod never assigned an SSH endpoint within `CREATE_TIMEOUT` (slow pull / dead host). | retry later — usually transient |

`FAIL` always exits `1`. `SKIP` is governed by `ON_SKIP` (env-var) /
`on-skip` (CI input), one of:

* `fail` (default) — exit `1` + `::error::` annotation. Job goes red.
* `warn`           — exit `0` + `::warning::` annotation. Job stays
  green; the run shows a yellow warning bubble in the PR check tab.
* `pass`           — exit `0`, no annotation (legacy lenient mode).

Unknown values silently coerce to `fail` so a typo never disables the
safer default. The summary lists the **instance that produced the outcome** in brackets,
so you can tell whether a `FAIL` correlates with a specific GPU type:

```
================================== SUMMARY =================================
totals: 4 PASS, 1 FAIL, 1 SKIP

  FAIL   runpod/pytorch:…cu1300-torch260… [RTX 5090] -- CUDA/GPU functional check failed
  SKIP   runpod/base:…rocm644-ubuntu2404… -- no capacity on any of 1 candidate instance type(s)
  PASS   runpod/base:…ubuntu2404 [CPU]
  PASS   runpod/base:…cuda1281-ubuntu2204 [RTX A4000]
  PASS   runpod/base:…cuda1281-ubuntu2404 [RTX A5000]
  PASS   runpod/base:…cuda1300-ubuntu2404 [RTX 4090]
```


## Common invocations

```bash
# Default manifest path is ./images, group filter is none.
./test_images.py

# Explicit manifest path
./test_images.py /path/to/my-images.yaml

# Only one group from a multi-group manifest
./test_images.py images.yaml pytorch

# Run 3 images in parallel (caps live pods at 3)
MAX_PARALLEL=3 ./test_images.py images.yaml

# Skip the 60s post-boot dwell to get faster iterations during debugging
DWELL_SEC=0 ./test_images.py images.yaml base_cpu

# Use a non-default SSH key
RUNPOD_SSH_KEY=~/.ssh/my_runpod_key ./test_images.py images.yaml

# Pin to a specific registry auth (avoid auto-pick when you have several)
REGISTRY_AUTH_NAME='dockerhub-prod' ./test_images.py images.yaml
# …or by id
REGISTRY_AUTH_ID='clxxxxxxxxxx' ./test_images.py images.yaml

# Keep the job green on SKIP but surface a yellow warning (GitHub
# Actions warning annotation in the PR check tab).
ON_SKIP=warn ./test_images.py images.yaml

# Fully lenient — script exits 0 on SKIP with no annotation.
ON_SKIP=pass ./test_images.py images.yaml
```

If a pod gets stuck (rare), `Ctrl-C` cleans up — `SIGINT`/`SIGTERM` are
trapped and trigger `cleanup_all()`, which `runpodctl pod delete`s
every pod the script created. Any pod the script missed will still
self-terminate within ~2 h via the `--terminate-after` clause set on
every `pod create`.


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

The `base_cpu` group is special: `runpodctl` 2.3.0 does not let us pick
a specific CPU flavor (`--gpu-id` is rejected for `--compute-type CPU`),
so the manifest needs ONLY an `images:` list for that group — no
`instances:` / `max_price_per_hour:` / `min_vram_gb:`. RunPod picks a
CPU flavor for us.


## Example manifest (the real one used in this repo)

Lives outside the repo at `~/tmp/runpod-scripts/testing/images` — the
manifest is environment-specific (image tags depend on which branch
you're testing). Annotated example covering every supported pattern:

```yaml
# CPU-only base image — no instances:, no budget, just images.
base_cpu:
    images:
    - runpod/base:1.0.6-dev-ubuntu2204
    - runpod/base:1.0.6-dev-ubuntu2404
    test_jupyter: true              # base CPU image still ships JupyterLab

# GPU base image, budget-selected. The CUDA functional check is auto-
# applied because the tag contains 'cuda1281' / 'cuda1290' / 'cuda1300'.
base_gpu:
    images:
    - runpod/base:1.0.6-dev-cuda1281-ubuntu2204
    - runpod/base:1.0.6-dev-cuda1281-ubuntu2404
    - runpod/base:1.0.6-dev-cuda1300-ubuntu2404
    max_price_per_hour: 1.0
    min_vram_gb: 16
    manufacturer: Nvidia
    test_jupyter: true

# autoresearch — torch lives in /opt/autoresearch/.venv, NOT importable
# from system python. The image-driven check picks nvidia-smi (because
# tag has 'cuda' but no 'pytorch' / 'torch\d' marker), which is what
# we want — we'd never get a clean torch import over SSH otherwise.
autoresearch:
    images:
    - runpod/autoresearch:1.0.6-dev-cuda1281-ubuntu2204
    - runpod/autoresearch:1.0.6-dev-cuda1281-ubuntu2404
    max_price_per_hour: 1.0
    min_vram_gb: 16
    manufacturer: Nvidia
    test_jupyter: true

# NGC base image. Tag '25.11' encodes no CUDA version — without
# min_cuda_version the scheduler picks any host and the container
# fails at startup with `nvidia-container-cli: cuda>=13.0`.
nvidia-pytorch:
    images:
    - runpod/nvidia-pytorch:1.0.6-dev-25.11
    max_price_per_hour: 1.0
    min_vram_gb: 16
    manufacturer: Nvidia
    min_cuda_version: "13.0"        # NGC 25.09+ PyTorch is built on cu13.0
    # No test_jupyter — NGC uses its own entrypoint, not our start.sh.

# AMD ROCm — explicit instance list because only MI300X carries ROCm.
rocm:
    images:
    - runpod/base:1.0.6-dev-rocm644-ubuntu2204-py310-pytorch251
    - runpod/base:1.0.6-dev-rocm644-ubuntu2404-py312-pytorch271
    instances:
    - MI300X
    test_jupyter: true

# runpod/pytorch — torch in system python, full torch.cuda check runs.
# PyTorch ≤ 2.6 wheels ship kernels only for sm_50…sm_90; Blackwell GPUs
# are sm_100/sm_120, so booting on one of them gives "no kernel image
# is available for execution on the device". Filter them out:
pytorch:
    images:
    - runpod/pytorch:1.0.6-dev-cu1281-torch260-ubuntu2204
    - runpod/pytorch:1.0.6-dev-cu1300-torch260-ubuntu2404
    max_price_per_hour: 1.0
    min_vram_gb: 16
    manufacturer: Nvidia
    test_jupyter: true
    exclude_instances:
    - "*Blackwell*"
```


## Environment variables

| var | default | description |
|---|---|---|
| `CLOUD_TYPE` | `SECURE` | `SECURE` or `COMMUNITY`. |
| `DISK_GB` | `100` | Container disk size for GPU pods. |
| `CPU_DISK_GB` | `20` | Container disk size for CPU pods. RunPod caps this per CPU flavor (20 GB on the cheapest, 30 GB on larger ones); 20 is the universal safe value. |
| `CPU_CANDIDATES` | `""` (uses `cpu-secure,cpu-community`) | CPU "instance candidates". `runpodctl pod create` doesn't accept `--vcpu` / `--mem` / `--cpu-flavor`, so we vary the axes it DOES expose for CPU: `--cloud-type` (SECURE vs COMMUNITY) and optional `--data-center-ids`. Each label becomes one candidate iterated by the same per-instance retry loop GPU groups use, so when SECURE is saturated COMMUNITY almost always has free CPU capacity. Format: `label:CLOUD[:DC1+DC2+…],label:CLOUD[:DC_CSV],…` (use `+` not `,` to separate DC ids inside one candidate so the outer csv stays unambiguous). CLOUD must be SECURE or COMMUNITY. Malformed entries are silently dropped; an empty/all-broken value falls back to the default 2-candidate list. |
| `RUNPOD_API_KEY` | _(from `~/.runpod/config.toml`)_ | Used for the GraphQL GPU pricing query. Set this in CI / containers without a config file. |
| `REGISTRY_AUTH_ID` | _(empty)_ | Explicit Docker Hub registry auth id to pass as `--registry-auth-id`. Overrides auto-discovery. |
| `REGISTRY_AUTH_NAME` | _(empty)_ | Display name to look up via `runpodctl registry list` when `REGISTRY_AUTH_ID` is not set. Falls back to the first entry. |
| `DWELL_SEC` | `60` | Extra seconds to wait after SSH becomes reachable, then re-probe SSH to catch containers that boot, accept SSH, then crash. Set 0 to skip the re-probe. |
| `CREATE_TIMEOUT` | `600` | Max seconds to wait for SSH to become reachable. Raise for ROCm workflows (`create-timeout: "1200"` on the action) — the official `rocm/pytorch:*` base images are 30-50GB and routinely take 8-15 minutes to pull. |
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

- image has `rocm` in ref
  → `rocm-smi` GPU enumeration + optional `hipcc --version`. Matched
  first so ROCm-pytorch images (built from `rocm/pytorch:*` where torch
  lives in a conda env not visible to the system `python`) don't get
  routed into the torch-import path and falsely fail with
  `ModuleNotFoundError`.
- image has `pytorch` / `torch\d` in ref
  → `torch.cuda.is_available` + matmul on device (catches broken drivers,
  missing libs, mismatched toolkit/driver versions). NVIDIA only at this
  point — ROCm was already handled above.
- image has `cuda` / `cu\d` (but no torch markers)
  → `nvidia-smi -L` + driver/memory query + `nvcc --version`. Covers base
  GPU images and `autoresearch` (whose torch is in a venv not reachable
  from the system Python we SSH into).
- otherwise (no GPU markers)
  → no check. Pod must still boot and survive `DWELL_SEC`.


## Jupyter check (opt-in via manifest `test_jupyter: true`)

Two stages, both must pass:

1. **In-pod.** SSH into the pod and `curl http://127.0.0.1:8888/api/status`
   with our token. Catches silent `start.sh` failures (e.g. `python3 -m
   jupyter` not finding the module on Ubuntu 22.04 — the kind of bug
   that prints `Jupyter Lab started` in the container log while no
   server is actually running).
2. **Public proxy.** From the test machine, `GET
   https://<pod-id>-8888.proxy.runpod.net/api/status` with the token.
   Catches port-type misconfigurations (`8888/tcp` instead of
   `8888/http` — the proxy never wires up non-http ports) and DNS /
   proxy registration issues that would prevent real users from
   reaching Jupyter from the RunPod console.


## Running in CI

The composite action at
[`.github/actions/smoke-test/action.yml`](../.github/actions/smoke-test/action.yml)
wraps everything in this script needs for a clean CI run:

1. Installs the pinned `runpodctl` binary (`runpodctl-version`,
   `runpodctl-sha256` inputs).
2. Configures the RunPod API key (`runpod-api-key` input) into
   `~/.runpod/config.toml`.
3. Writes the `ssh-private-key` input to `~/.ssh/id_runpod` and exports
   `RUNPOD_SSH_KEY` so the in-pod CUDA probe and log fetch work.
4. Generates a manifest from the `image-refs` JSON array using
   `.github/scripts/generate_test_manifest.py`, applying the
   `profile`, `budget-usd-per-hour`, `min-vram-gb`, `manufacturer`,
   `test-jupyter`, and `exclude-instances` inputs.
5. Invokes `python3 tests/test_images.py <generated-manifest>` with
   `MAX_PARALLEL=<max-parallel>` and `continue-on-error: true` so a
   single broken image doesn't take the whole pipeline down.

Typical caller (from a per-image-family build workflow):

```yaml
- uses: ./.github/actions/smoke-test
  with:
    image-refs: ${{ toJSON(steps.bake.outputs.image-refs) }}
    profile: gpu                            # base = split CPU/GPU (only for runpod/base) | gpu = single base_gpu group (everything else)
    runpod-api-key: ${{ secrets.RUNPOD_API_KEY }}
    ssh-private-key: ${{ secrets.RUNPOD_SSH_KEY }}
    budget-usd-per-hour: "1.0"
    min-vram-gb: "16"
    manufacturer: Nvidia
    test-jupyter: "true"
    exclude-instances: |
      *Blackwell*
    max-parallel: "3"
```

The full input reference lives in the action's own `description:`
fields.


## Troubleshooting

| symptom in logs | likely cause | fix |
|---|---|---|
| `runpodctl not found in PATH` | `runpodctl` binary missing | install from <https://github.com/runpod/runpodctl/releases>, put on `$PATH` |
| `runpodctl is not authenticated. Run 'runpodctl doctor'` | API key not configured or expired | `runpodctl config --apiKey <KEY>` |
| `warn: no GPU pricing data` | `RUNPOD_API_KEY` not set and no `~/.runpod/config.toml` | set `RUNPOD_API_KEY` or run `runpodctl config --apiKey` |
| `warn: no registry auth configured` | no Docker Hub auth registered | `runpodctl registry add` (paid Hub account strongly recommended for parallel runs) |
| every group says `no capacity on any of N candidate instance type(s)` | budget too low / VRAM too high / region saturated | raise `max_price_per_hour`, drop `min_vram_gb`, or set explicit `instances:` |
| only the `base_cpu` group says `no capacity` while GPU groups pass | the cloud(s) you target don't have CPU capacity right now | by default we already try SECURE then COMMUNITY. If both are full, add DC-pinned candidates: `CPU_CANDIDATES="cpu-secure:SECURE,cpu-community:COMMUNITY,cpu-eu:COMMUNITY:EU-RO-1+EU-NL-1,cpu-us:COMMUNITY:US-OR-1"` |
| pod stays in `ssh endpoint not assigned yet` past `STALL_HINT_AFTER` | slow image pull or Docker Hub `toomanyrequests` | add registry auth, reduce `MAX_PARALLEL`, or wait 6 h for the Hub rate limit to reset |
| `ssh_probe=FAIL — Permission denied (publickey)` | wrong SSH key | export `RUNPOD_SSH_KEY=/path/to/private/key` whose public half is on the RunPod account |
| `pod entered TIMEOUT state` repeatedly on Blackwell GPUs for a `pytorch` group | PyTorch ≤ 2.6 has no `sm_100`/`sm_120` kernels | add `exclude_instances: ["*Blackwell*"]` to the group |
| `nvidia-container-cli: requirement error: unsatisfied condition: cuda>=X.Y` in pod logs | image needs a newer driver than the host has | set `min_cuda_version: "X.Y"` in the manifest (only needed for tags without a `cuXYZW`/`cudaXYZW` marker) |
| `jupyter check (in-pod) FAILED -- start.sh did not bring up JupyterLab` | `start.sh` is launching Jupyter with the wrong Python interpreter (classic Ubuntu 22.04 `python3` → 3.10 vs `python` → 3.12) | fix `container-template/start.sh` to use `python -m jupyter lab` |
| `jupyter check (public proxy) FAILED` but in-pod check passed | port exposed as `8888/tcp` instead of `8888/http`, OR proxy hasn't registered the pod yet | check `pod create --ports` arg; bump `JUPYTER_PROXY_TIMEOUT` if proxy is just slow |
| script hangs at `Cleaning up N leftover pod(s)…` | RunPod API is slow to respond to delete | wait it out; `--terminate-after` (~2 h) is the backstop and will kill anything we missed |


## Exit code

`0` only when every image PASSed, OR when only SKIPs happened and
`ON_SKIP ∈ {warn, pass}`. `1` if any image FAILed (broken container —
always fatal), or if any image SKIPped under the default `ON_SKIP=fail`.

SKIPs mean the smoke test never actually ran on the image (RunPod had no
capacity on every candidate, or every candidate landed on a stuck host)
— that's effectively zero validation, so the default is strict.
Override with:

* `ON_SKIP=warn` to keep the job green but get a GitHub Actions warning
  annotation in the PR check tab (visible signal without blocking the PR).
* `ON_SKIP=pass` to fully suppress the signal (no annotation at all).

Unknown values silently coerce to `fail`.
