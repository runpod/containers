# Smoke tests for RunPod container images

Spins up each image on a real RunPod pod, waits for it to stay healthy
for `DWELL_SEC` seconds, runs image-appropriate CUDA, HTTP, and optional
ComfyUI functional checks, then terminates the pod. Designed to catch the failure modes that **only
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
├── comfyui/                ← ComfyUI functional-test models and workflow
└── runpod_smoke/
    ├── config.py           ← env vars, sentinels, shared mutable state
    ├── log.py              ← thread-tagged logging
    ├── manifest.py         ← parser + value normalizers
    ├── api.py              ← REST API v2 client: auth, requests, error classification
    ├── instances.py        ← GPU/CPU catalog, budget resolution, exclude filter, CUDA axis
    ├── pod.py              ← pod create/lifecycle/signals, registry auth
    ├── checks.py           ← SSH/proxy checks, CUDA functional check, REST API v2 log diagnostics
    ├── comfyui.py          ← ComfyUI proxy, model, workflow, and PNG checks
    └── runner.py           ← test_pair / test_image (per-image orchestration)
```


## Prerequisites

1. **Python ≥ 3.9** (stdlib only — no pip install needed).
2. **A RunPod API key** with **pod-management** permissions, in either
   `RUNPOD_API_KEY` or `~/.runpod/config.toml` as `apikey = '...'`:

   ```bash
   export RUNPOD_API_KEY=<YOUR_RUNPOD_API_KEY>
   ```

   Generate one at <https://www.runpod.io/console/user/settings>. There is
   no CLI dependency — everything goes through REST API v2 (see
   `runpod_smoke/api.py`). The key is validated at startup with
   `GET /v2/account/ssh-keys`; a bad key fails fast before any pod is
   created.

3. **SSH key registered on your RunPod account.** `test_images.py`
   probes every pod over SSH for the real readiness signal and the
   GPU/CUDA functional check. Register the public half at
   <https://www.runpod.io/console/user/settings#ssh-keys> and keep the
   private half at one of `~/.runpod/ssh/runpodctl-ssh-key`,
   `~/.ssh/runpodctl-ssh-key`, or point `RUNPOD_SSH_KEY` at it.

   The private key file must be mode `600` — OpenSSH refuses
   group/world-readable keys, and the SSH probe will fail every pod
   with no obvious reason.

4. **(Recommended)** A Docker Hub registry credential on the account.
   RunPod datacenters share an anonymous Hub IP pool that hits the
   `toomanyrequests` rate limit fast — without auth, parallel runs in
   particular produce a wave of "image pull backoff" failures that look
   like image bugs but aren't. The script auto-discovers the first entry
   from `GET /v2/registries`; pin a specific one with `REGISTRY_AUTH_ID`
   or `REGISTRY_AUTH_NAME`.


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

1. `loaded N GPU types from GET /v2/catalog/gpus` — startup catalog query
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
| 1 | `POST /v2/pods` with `gpu.id` (or an auto-picked `cpu.id` + `vcpuCount`), `disk`, `ports`, `startSsh`, registry credential, and either `gpu.minCudaVersion` or `gpu.allowedCudaVersions`. Transient failures (429, 5xx, transport) are retried up to `CREATE_RETRIES` with linear backoff. | `UNAVAILABLE` (no capacity — try next instance) / `CREATE_FAIL` (bad image tag, auth, malformed request — any non-capacity, non-transient error after retries) |
| 2 | Poll `GET /v2/pods/{id}` until `status` is `RUNNING`, `ssh.direct` is populated, and one-shot `ssh root@host -p port 'echo ready'` succeeds. SSH is the readiness signal; `status` is the real observed `PodStatus`, so terminal `EXITED`/`ERROR`/`TERMINATED` stop the poll immediately. | `FAIL` on a terminal status, or when the system log shows a container-init rejection; `STUCK` if no SSH endpoint within `CREATE_TIMEOUT` |
| 3 | **CUDA functional check** over SSH — see [Functional check](#functional-check). Image-driven: pytorch ref → `torch.cuda` + matmul; cuda/rocm ref → `nvidia-smi` + `nvcc`; neither → skip | `FAIL` (image is broken — stop iterating; another GPU won't help) |
| 4 | **JupyterLab proxy-first check** (only when `test_jupyter: true`) — checks the public proxy; SSH probes `/api/status` only to diagnose a proxy failure | `FAIL` (Jupyter did not start, or is not exposed as `8888/http`) |
| 5 | **Generic proxy-first port checks** (optional `test_ports`) — each service must return HTTP 200 through `https://<pod-id>-<port>.proxy.runpod.net/`; SSH diagnoses failures | `FAIL` (service unavailable or incorrectly exposed) |
| 6 | **ComfyUI proxy-first reachability** (only when `test_comfyui: true`) — public `:8188` first; SSH diagnoses a failed proxy check | `FAIL` (ComfyUI unavailable or incorrectly exposed) |
| 7 | **ComfyUI functional generation** (only when `test_comfyui_functional: true`) — provision models via RunpodDirect, execute the workflow, then validate a real PNG through the public proxy | `FAIL` (model, workflow, node, GPU, or output failure) |
| 8 | **REST API v2 container-log scan** — backfill stdout and scan it for configured error/crash markers | `FAIL` on a matching marker or an unverified empty API response |
| 9 | Sleep `DWELL_SEC`, re-probe SSH (catches "boots fine then crashes after 30s") | `FAIL` if SSH stops responding |
| 10 | Re-probe ComfyUI `/system_stats` after dwell, then re-scan REST API v2 logs | `FAIL` if ComfyUI died during dwell, or logs contain a new error marker |
| 11 | `dump_pod_logs` — API container logs, API system-log error markers, and GPU SMI over SSH | _(diagnostic only)_ |
| 12 | `DELETE /v2/pods/{id}` (always — even on Ctrl-C / exception via `atexit` + signal handlers). A 404 counts as success. | _(diagnostic only)_ |

`test_image()` then iterates over the next instance candidate when the
result was `UNAVAILABLE` or `STUCK`, and short-circuits on `PASS`,
`FAIL`, or `CREATE_FAIL`. With `check_all_gpu: true`, each resolved GPU is
instead run as an independent job, so the summary shows compatibility across
the full selected GPU set. Adding `cuda_versions:` splits it further — one
job per (GPU, CUDA version) — see [CUDA axis](#cuda-axis).


## Outcomes

The summary at the end of every run groups results into three buckets.
The granular per-pod outcomes below collapse into them:

| summary | per-pod outcome | what it means | what to do |
|---|---|---|---|
| `PASS` | `PASS` | Image booted, all checks passed, survived dwell. | nothing |
| `FAIL` | `FAIL` | Pod was created and the container itself proved broken (CUDA check failed, JupyterLab didn't start, crashed during dwell, etc.). Moving to another GPU won't help — the image is the problem. | fix the image |
| `FAIL` | `CREATE_FAIL` | Pod-create returned a non-capacity, non-transient orchestrator error (bad image tag, registry auth, malformed request, missing CUDA version). | fix the manifest / image ref / auth |
| `FAIL` | `FAIL` (container init) | `nvidia-container-cli` rejected the container in the prestart hook — typically the image's `NVIDIA_REQUIRE_CUDA` floor is above the host driver, e.g. a `cu1290` image pinned to CUDA 12.4. Deterministic, so no other instance type is tried. | pin a CUDA version the image supports, or fix the image's requirement |
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

# Run the checked-in ComfyUI end-to-end example. This downloads the configured
# model and can take several minutes.
python3 ./tests/test_images.py ./tests/comfyui/images.example.yaml comfyui
```

If a pod gets stuck (rare), `Ctrl-C` cleans up — `SIGINT`/`SIGTERM` are
trapped and trigger `cleanup_all()`, which deletes every pod the script
created.

For pods the script misses, the real safety net is CI-side: a
`cancel-in-progress` PR cancel can SIGKILL the runner before
`cleanup_all()` finishes, so the `.github/workflows/reap-pods.yml` cron
sweeps any `smoketest-*` pod older than ~60 min and deletes it. It reads
each pod's age from its name, so it never touches a human's pod.

> **There is no server-side auto-terminate.** The old CLI accepted
> `--terminate-after <RFC3339>`; REST API v2 has no equivalent field, so
> `reap-pods.yml` is now the *only* backstop against a leaked pod billing
> indefinitely. Keep that cron healthy.


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
    check_all_gpu: true       # test every matching GPU independently
    test_jupyter: true        # opt-in JupyterLab in-pod + proxy check
    test_ports:               # optional generic HTTP services
    - 8080
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
| `min_cuda_version` | `X.Y` floor sent as `gpu.minCudaVersion`. Used as a **fallback** when the image tag doesn't encode a CUDA version (e.g. NGC `nvidia-pytorch:25.11`); tags like `cu1281` / `cuda1281` / `cuda13.0` are parsed and win. Superseded by `cuda_versions` — the API rejects both fields on one request. |
| `cuda_versions` | `all`, or a list of exact `X.Y` versions. Turns on the [CUDA axis](#cuda-axis): each candidate GPU is tested once per version, pinned with `gpu.allowedCudaVersions`. Default: unset (no axis). |
| `check_all_gpu` | `true` / `false` — use every catalog GPU matching `min_vram_gb` and `manufacturer`, with one independent result row per `(image, GPU)`. Mutually exclusive with budget selection in generated manifests and potentially expensive. Default: `false`. |
| `test_jupyter` | `true` / `false` — when true, the pod is created with `JUPYTER_PASSWORD=admin` in env and HTTP port 8888 exposed, then the script SSHes in and verifies JupyterLab is actually listening. Use for groups whose images use `container-template/start.sh` (`runpod/base`, `runpod/pytorch`, `runpod/autoresearch`, `rocm`). Skip for NGC `nvidia-pytorch` (different entrypoint). Default: `false`. |
| `test_ports` | Optional list of HTTP ports. Each is exposed as `<port>/http` and must return HTTP 200 through the RunPod public proxy. On a proxy failure, the test probes `127.0.0.1:<port>` over SSH to distinguish a service startup failure from an exposure/configuration error. |
| `test_comfyui` | `true` / `false` — exposes `8188/http` and runs a labelled proxy-first ComfyUI reachability check. After dwell it verifies `/system_stats` again because the container can survive a ComfyUI crash. Default: `false`. |
| `test_comfyui_functional` | `true` / `false` — implies `test_comfyui`; downloads/verifies the configured model through ComfyUI-RunpodDirect, POSTs the workflow, waits for completion, then validates a non-empty PNG from `/view`. The ComfyUI workflow enables it for both PR and release runs. |

The `base_cpu` group is special: the manifest needs ONLY an `images:`
list for that group — no `instances:` / `max_price_per_hour:` /
`min_vram_gb:`. The flavor is chosen from `GET /v2/catalog/cpus` by
`instances.pick_cpu_flavor()` — cheapest per-vCPU flavor whose range
admits `CPU_VCPU_COUNT`, preferring better-reported availability. Pin one
with `CPU_FLAVOR_ID` if you need a specific tier.

The functional workflow and model manifest live under `tests/comfyui/`.
Set `COMFYUI_SAVE_DIR` to retain the validated PNG locally; the composite
action uploads it when `save-comfyui-images: "true"`.


## CUDA axis

`--min-cuda-version` / `gpu.minCudaVersion` is only a **floor**: the
scheduler may place the pod on any host at or above it. In practice that
means a `cu1281` image gets tested on whatever driver RunPod happens to
have free — observed values for the same GPU have ranged from 12.8 to
13.2 across two runs an hour apart. So a plain `PASS` says "works
somewhere", not "works on 12.8".

`cuda_versions:` fixes that by pinning `gpu.allowedCudaVersions`, which
the API matches **exactly**:

```yaml
base_gpu:
    images:
    - runpod/pytorch:1.2.0-cu1281-torch2121-ubuntu2404
    check_all_gpu: true
    manufacturer: Nvidia
    min_vram_gb: 16
    cuda_versions: all        # or: a list of exact versions
```

```yaml
    cuda_versions:
    - "12.8"
    - "13.0"
```

Two expansion modes, depending on `check_all_gpu`:

| | one job per | short-circuit |
|---|---|---|
| `cuda_versions` + `check_all_gpu: true` | **(GPU, version)** — the full matrix | no |
| `cuda_versions` alone | **version**, candidates = GPUs offering it | yes, first PASS wins |

The second mode exists so that adding an axis to a budget-filtered group
doesn't silently turn one pod into a product of ~20 cards × N versions.

**Only pairings the catalog reports capacity for are attempted.**
`GET /v2/catalog/gpus?include=AVAILABILITY&product=POD` returns, per GPU,
`cudaVersions: [{version, available}]`. Because matching is exact, pinning
a version nobody reports yields a capacity error rather than a fallback —
so unavailable pairings are dropped at planning time instead of burning a
pod each. A GPU with no usable version is recorded as a SKIP row and
appears in the matrix as a full row of `·`.

**`cudaVersions` is scoped to one cloud tier.** The catalog is fetched with
`cloud=$CLOUD_TYPE` (default `SECURE`), and a GPU with no host in that tier
comes back with an empty version list — 16 of 47 catalog GPUs are
community-only, including every GeForce card and both V100s. Pods are
created in the same tier, so those GPUs are genuinely untestable in that
run, and the SKIP note names the tier rather than claiming the API reports
nothing. The tiers do not nest (`A40`, `L4`, `H100 SXM`, `B200` and `B300`
have no community hosts), so covering the whole catalog needs both.

`CLOUD_TYPE` therefore takes a list, or `ALL`, and one invocation sweeps
each tier:

```sh
CLOUD_TYPE=ALL ON_SKIP=pass python3 tests/test_images.py <manifest> <group>
```

Planning happens once per tier, since availability, CUDA versions and
prices are all scoped to one; the resulting jobs then share a single worker
pool, and each job carries its tier through to `POST /v2/pods`. Practical
consequences:

* `MAX_CUDA_COMBOS` caps the **combined** job count, so a two-tier sweep
  can't silently double the pod count.
* The summary labels every row with its tier, and the step summary emits
  one GPU × CUDA pivot per tier — the same (GPU, CUDA) pairing can be
  tested in both, and one grid would drop one of the two outcomes.
* CPU groups are planned only once. Their candidate labels already encode a
  tier each (see `CPU_CANDIDATES`), so they ignore this axis.

`MAX_CUDA_COMBOS` (default 120) caps the fan-out; jobs past the cap are
dropped with a warning.

The axis is NVIDIA-only — AMD cards report no `cudaVersions`, and turning
it on for a ROCm sweep produces zero jobs plus a `::warning::` saying so.

### Result matrix

With an axis active, the job's step summary gains a pivot table on top of
the flat list:

```
### GPU x CUDA

| GPU               | CUDA 12.4 | CUDA 12.8 | CUDA 13.0 | CUDA 13.2 |
|-------------------|-----------|-----------|-----------|-----------|
| A100 SXM          | ✅        | ✅        | ✅        | ·         |
| B200              | ·         | ·         | ✅        | ·         |
| PRO 6000 MIG 48GB | ·         | ·         | ✅        | ✅        |
| RTX A6000         | ·         | ✅        | ⚠️        | ·         |
| Tesla V100        | ·         | ·         | ·         | ·         |

✅ pass · ❌ fail · ⚠️ skip (pod attempted, no capacity) · · not attempted
```

`⚠️` and `·` are different events: yellow means a pod was created for that
exact pairing and RunPod had no capacity; a dot means the pairing never
reached a create because the catalog said so up front.

Both the table and the flat list are always written to
`$GITHUB_STEP_SUMMARY`, which is readable on the run page without
permission to download job logs. Set `SMOKE_RESULTS_JSON` (the composite
action does, behind `upload-results-json`) to also emit a machine-readable
report for diffing runs:

```json
{
  "generated_at": "2026-08-31T10:03:03Z",
  "totals": { "PASS": 28, "FAIL": 0, "SKIP": 25 },
  "results": [
    { "image": "…", "status": "PASS", "instance": "A40",
      "cuda": "13.0", "requested_cuda": "13.0", "note": "" }
  ]
}
```

`cuda` is what the host reported (`Pod.cudaVersion`); `requested_cuda` is
what we pinned. They differ only if the API ever stops honouring the pin,
which is worth knowing.


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
| `CLOUD_TYPE` | `SECURE` | `SECURE`, `COMMUNITY`, both as a comma list, or `ALL`. Multiple tiers are planned and swept in one invocation — see [CUDA axis](#cuda-axis). |
| `DISK_GB` | `100` | Container disk size for GPU pods. |
| `CPU_DISK_GB` | `20` | Container disk size for CPU pods. RunPod caps this per CPU flavor (20 GB on the cheapest, 30 GB on larger ones); 20 is the universal safe value. |
| `CPU_CANDIDATES` | `""` (uses `cpu-secure,cpu-community`) | CPU "instance candidates". The flavor comes from `pick_cpu_flavor()`; what varies between candidates is placement — cloud (SECURE vs COMMUNITY) and optional data centres. Each label becomes one candidate iterated by the same per-instance retry loop GPU groups use, so when SECURE is saturated COMMUNITY almost always has free CPU capacity. Format: `label:CLOUD[:DC1+DC2+…],label:CLOUD[:DC_CSV],…` (use `+` not `,` to separate DC ids inside one candidate so the outer csv stays unambiguous). CLOUD must be SECURE or COMMUNITY. Malformed entries are silently dropped; an empty/all-broken value falls back to the default 2-candidate list. |
| `RUNPOD_API_KEY` | _(from `~/.runpod/config.toml`)_ | Bearer token for every REST API v2 call. Set this in CI / containers without a config file. |
| `MAX_CUDA_COMBOS` | `120` | Cap on the (GPU, CUDA) fan-out. Jobs past it are dropped with a warning so a stray `cuda_versions: all` can't run for a day. |
| `CPU_VCPU_COUNT` | `4` | vCPUs requested for CPU pods. Must be a power of two inside the chosen flavor's `vcpu.min..max`. |
| `CPU_FLAVOR_ID` | _(empty)_ | Pin a CPU flavor (e.g. `cpu3c`) instead of auto-picking the cheapest fitting one from `GET /v2/catalog/cpus`. |
| `SMOKE_RESULTS_JSON` | _(empty)_ | Path to write the machine-readable result report to. Empty = don't write it. The markdown step summary is written regardless. |
| `REGISTRY_AUTH_ID` | _(empty)_ | Explicit Docker Hub registry auth id to pass as `--registry-auth-id`. Overrides auto-discovery. |
| `REGISTRY_AUTH_NAME` | _(empty)_ | Display name to look up via `GET /v2/registries` when `REGISTRY_AUTH_ID` is not set. Falls back to the first entry. |
| `DWELL_SEC` | `60` | Extra seconds to wait after SSH becomes reachable, then re-probe SSH to catch containers that boot, accept SSH, then crash. Set 0 to skip the re-probe. |
| `CREATE_TIMEOUT` | `600` | Max seconds to wait for SSH to become reachable. Raise for ROCm workflows (`create-timeout: "1200"` on the action) — the official `rocm/pytorch:*` base images are 30-50GB and routinely take 8-15 minutes to pull. |
| `POLL_INTERVAL` | `10` | Poll cadence for SSH probes. |
| `MAX_PARALLEL` | `1` | How many images to smoke-test concurrently. Each worker holds at most one pod, so this caps simultaneous live pods. Keep modest to avoid RunPod rate limits and surprise bills. |
| `CREATE_RETRIES` | `3` | Retry pod-create up to N times on transient RunPod 5xx errors (`Something went wrong`, 502/503). Capacity shortages are NOT retried. |
| `CREATE_RETRY_BACKOFF` | `10` | Seconds between retries (linear backoff). |
| `STALL_HINT_AFTER` | `180` | Seconds without an SSH endpoint before the script prints a hint about slow pulls / possible Docker Hub rate limit. |
| `LOG_ERROR_SCAN` | `1` | `1`/`0` — scan REST API v2 container logs for error markers after the functional checks. |
| `LOG_ERROR_PATTERN` | `\berr(or)?s?\b\|\bcrash(ed\|es\|ing)?\b` | Case-insensitive regex used by the container-log scan. |
| `LOG_API_TAIL` | `1000` | Number of historical lines to fetch from the REST API v2 log stream. |
| `SYS_LOG_ERROR_PATTERN` | error/failure/crash regex | Case-insensitive regex for host-side REST API system-log diagnostics during a failed boot. |
| `SSH_LOG_FETCH` | `1` | `1`/`0` — fetch only the GPU SMI diagnostic over SSH. Container logs use REST API v2. |
| `RUNPOD_SSH_KEY` | _(empty)_ | Path to the private key matching a public key registered on the account (`startSsh` injects those as `PUBLIC_KEY`). Auto-discovered from `~/.runpod/ssh/` and `~/.ssh/` if unset. Must be mode `600`. |
| `JUPYTER_WAIT_TIMEOUT` | `30` | Seconds the in-pod Jupyter probe waits for `:8888` to bind. |
| `JUPYTER_PROXY_TIMEOUT` | `60` | Seconds the proxy probe retries while RunPod's ingress registers the new pod. |
| `PORT_WAIT_TIMEOUT` | `300` | Seconds the SSH diagnostic probe waits for a `test_ports` service to bind and return HTTP 200. |
| `PORT_PROXY_TIMEOUT` | `300` | Seconds the public-proxy check retries each `test_ports` service before failing. |
| `COMFYUI_PORT` | `8188` | HTTP port exposed for the ComfyUI public-proxy checks. |
| `COMFYUI_WORKFLOW` | `tests/comfyui/workflows/gsl_starter_1_1.api.json` | API workflow submitted by the functional test. |
| `COMFYUI_MODELS_MANIFEST` | `tests/comfyui/models.json` | Models provisioned through ComfyUI-RunpodDirect before the workflow runs. |
| `COMFYUI_WAIT_TIMEOUT` | `300` | Maximum wait for ComfyUI `/system_stats`. |
| `COMFYUI_ROUTES_TIMEOUT` | `120` | Maximum wait for ComfyUI-RunpodDirect routes. |
| `COMFYUI_DOWNLOAD_TIMEOUT` | `1800` | Maximum wait for each functional-test model download. |
| `COMFYUI_GEN_TIMEOUT` | `600` | Maximum wait for workflow execution and its image output. |
| `COMFYUI_SAVE_DIR` | _(empty)_ | Directory where validated ComfyUI PNGs are retained for artifact upload. |


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

The public proxy is checked first. If it returns HTTP 200, the service is
both running and exposed as `8888/http`, so SSH is skipped. On failure the
test SSHes in and probes `/api/status` to distinguish a Jupyter startup
problem from an HTTP exposure/proxy problem.


## Running in CI

The composite action at
[`.github/actions/smoke-test/action.yml`](../.github/actions/smoke-test/action.yml)
wraps everything in this script needs for a clean CI run:

1. Exports the RunPod API key (`runpod-api-key` input) as
   `RUNPOD_API_KEY` for every later step. No CLI to install.
2. Writes the `ssh-private-key` input to `~/.ssh/id_runpod` and exports
   `RUNPOD_SSH_KEY` so the in-pod CUDA probe and log fetch work.
3. Generates a manifest from the `image-refs` JSON array using
   `.github/scripts/generate_test_manifest.py`, applying the
   `profile`, `budget-usd-per-hour`, `min-vram-gb`, `manufacturer`,
   `test-jupyter`, `test-ports`, `test-comfyui`,
   `test-comfyui-functional`, `check-all-gpu`, `cuda-versions`,
   `min-cuda-version`, and `exclude-instances` inputs.
4. Invokes `python3 tests/test_images.py <generated-manifest>` with
   `MAX_PARALLEL=<max-parallel>`. A failed image makes the smoke-test
   action fail, which prevents a release from being created.

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
    exclude-instances: |          # fnmatch on GPU DISPLAY names
      B200                        # ("*Blackwell*" matches nothing —
      B300                        #  display names don't contain it)
      RTX PRO *
    max-parallel: "3"

    # Opt in to the GPU x CUDA matrix (see "CUDA axis"):
    # check-all-gpu: "true"
    # cuda-versions: all
    # upload-results-json: "true"
```

The full input reference lives in the action's own `description:`
fields.


## Troubleshooting

| symptom in logs | likely cause | fix |
|---|---|---|
| `no RunPod API key — set RUNPOD_API_KEY…` | key missing from env and `~/.runpod/config.toml` | `export RUNPOD_API_KEY=<KEY>` |
| `RunPod API rejected the key (HTTP 401…)` | key expired or lacks pod-management permission | regenerate at <https://www.runpod.io/console/user/settings> |
| `warn: no GPU catalog` | `GET /v2/catalog/gpus` failed — usually a bad/absent key | fix the key; budget and `check_all_gpu` selection are disabled without it |
| `warn: no registry auth configured` | no Docker Hub credential on the account | add one in the RunPod console (paid Hub account strongly recommended for parallel runs) |
| every pod SKIPs with an SSH failure | private key not mode `600`, or its public half isn't registered | `chmod 600 <key>`; verify the fingerprint appears in `GET /v2/account/ssh-keys` |
| `cuda_versions is set but none of the N candidate GPUs reports any CUDA version in the SECURE cloud` | CUDA axis on a ROCm/AMD sweep, or every candidate lives in the other cloud tier | drop `cuda_versions` for ROCm — the axis is NVIDIA-only; otherwise rerun with the other `CLOUD_TYPE` |
| `GPU not covered: not offered in the SECURE cloud` | community-only GPU (all GeForce cards, both V100s, `A100 SXM 40GB`) — `cudaVersions` is scoped to `CLOUD_TYPE` | use `CLOUD_TYPE=ALL` to sweep both tiers in one run; the note says `(covered by the COMMUNITY pass)` when it already did |
| every group says `no capacity on any of N candidate instance type(s)` | budget too low / VRAM too high / region saturated | raise `max_price_per_hour`, drop `min_vram_gb`, or set explicit `instances:` |
| only the `base_cpu` group says `no capacity` while GPU groups pass | the cloud(s) you target don't have CPU capacity right now | by default we already try SECURE then COMMUNITY. If both are full, add DC-pinned candidates: `CPU_CANDIDATES="cpu-secure:SECURE,cpu-community:COMMUNITY,cpu-eu:COMMUNITY:EU-RO-1+EU-NL-1,cpu-us:COMMUNITY:US-OR-1"` |
| pod stays in `ssh endpoint not assigned yet` past `STALL_HINT_AFTER` | slow image pull or Docker Hub `toomanyrequests` | add registry auth, reduce `MAX_PARALLEL`, or wait 6 h for the Hub rate limit to reset |
| `ssh_probe=FAIL — Permission denied (publickey)` | wrong SSH key | export `RUNPOD_SSH_KEY=/path/to/private/key` whose public half is on the RunPod account |
| `pod entered TIMEOUT state` repeatedly on Blackwell GPUs for a `pytorch` group | PyTorch ≤ 2.6 has no `sm_100`/`sm_120` kernels | add `exclude_instances: ["*Blackwell*"]` to the group |
| `nvidia-container-cli: requirement error: unsatisfied condition: cuda>=X.Y` in pod logs | image needs a newer driver than the host has | set `min_cuda_version: "X.Y"` in the manifest (only needed for tags without a `cuXYZW`/`cudaXYZW` marker) |
| `jupyter check (in-pod) FAILED -- start.sh did not bring up JupyterLab` | `start.sh` is launching Jupyter with the wrong Python interpreter (classic Ubuntu 22.04 `python3` → 3.10 vs `python` → 3.12) | fix `container-template/start.sh` to use `python -m jupyter lab` |
| `jupyter check (public proxy) FAILED` but in-pod check passed | port exposed as `8888/tcp` instead of `8888/http`, OR proxy hasn't registered the pod yet | check `pod create --ports` arg; bump `JUPYTER_PROXY_TIMEOUT` if proxy is just slow |
| script hangs at `Cleaning up N leftover pod(s)…` | RunPod API is slow to respond to delete | wait it out; the `reap-pods.yml` cron sweeps anything we miss (`--terminate-after` is unreliable — dropped for CPU pods, not honored promptly for GPU — so don't count on it) |


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
