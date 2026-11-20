# Template staleness playbook

Instructions for the weekly staleness scraper (`.github/workflows/staleness-scraper.yml`).
You are running headless in GitHub Actions. Your job: find upstream releases we do
not yet ship, and, where you can verify the build inputs exist, open a draft PR that
adds them following the exact conventions already in the repo.

Covered families: **pytorch**, **comfyui**, **autoresearch**, **base**,
**pytorch-cluster**, **ray-cluster** (detection only), **filebrowser**,
**k3s-node**, and the four sandboxes (**sandbox-ubuntu**, **sandbox-browser**,
**sandbox-harbor**, **sandbox-openclaw**). Ignore all others: **rocm** and
**nvidia-pytorch** track upstream vendor images by hand, and **base**'s CUDA list
is deliberately human-owned (see its section).

## Ground rules

- A bump edits the family's `docker-bake.hcl` (or its `Dockerfile`) and, for every
  family whose `README.md` lists versions, that README too. The README lists are
  hand-maintained (the `update-readme` action only pushes README.md to the Runpod
  template API, it does not generate them). Each family section below says exactly
  what its README needs, or that it needs none.
- Never replace a **shipped version** with a newer one. Where a pin drives its own
  image tag — the entries of `TORCH_META`, `COMFYUI_VERSIONS`, `FILEBROWSER_VERSIONS`
  — add the new one **alongside** the existing ones and leave the old entries
  untouched; users pin those tags and we keep shipping them. A pin for a component
  *inside* an image (runpodctl, get-pip, the monitoring daemons, Node, Playwright,
  Harbor, k3s) has no such tag and is a plain in-place bump. Each section below says
  which kind it is.
- When you bump a pin that is a git commit SHA, always add a short trailing
  comment. Use the version when the commit maps to a release tag
  (`FOO_SHA = "abc123..." # v1.2.3`); when it is untagged, use the commit date
  instead (`FOO_SHA = "abc123..." # 2026-10-20`).
- When you cannot verify that a build input (a wheel, a release asset, a checksum)
  actually exists, do NOT guess it in. Leave it out and say so in the PR body.
  The CUDA/wheel matrix is hand-curated, a wrong pin fails the build.
- Before finalizing a bump, check it is compatible with the pins in the family's
  `requirements.txt` (and base's `requirements.txt` for families that build FROM
  base). If the new version conflicts with a pinned dependency, do not just bump:
  flag the conflict in the PR body.
- Only add a release that is at least **2 days old** (check its upstream publish
  date). A newer release may get a quick follow-up patch; skip it this run and it
  gets picked up next week once it has settled. If the newest release is too young
  but a settled older one is still newer than ours, add that one.
- If a family is already current, do nothing for it. Never open an empty PR.
- Branch off `develop` and open every PR against `develop`, never `main`
  (`gh pr create --base develop --draft`). The checkout is already on develop, so
  `git checkout -b staleness-scraper/<family>` branches from it.
- One branch and one draft PR per stale family. Use a stable branch name
  `staleness-scraper/<family>` and add the label `staleness-scraper` to the PR, so
  the job can find its own PRs later. Title like `feat: pytorch <version>`.
- Before opening a PR, check for an existing open PR from this job for that family
  (`gh pr list --label staleness-scraper --head staleness-scraper/<family> --state open`).
  If one exists, do NOT open a second one: update that branch (commit the new edits
  and push to it) and refresh the PR title and body. Only open a new PR when none
  is open for the family.
- After editing, run `docker buildx bake -f official-templates/shared/versions.hcl
  -f official-templates/<family>/docker-bake.hcl --print` as a syntax check. If it
  errors on the HCL itself, fix it. Build/runtime correctness is proven later by CI.
- When you finish, write your outcome to `/tmp/scraper-status` with the Write tool:
  exactly `ok` if you completed this family (opened or updated its PR, confirmed it
  is already current with nothing to do, or — for a detection-only check — reported
  what you found to the job summary), or `failed: <one-line reason>` if
  anything blocked you (a denied tool, an input you could not verify, a git or PR
  step that failed, or the family not being present on the base branch). The job
  reads this file and goes red unless it is exactly `ok`.

## pytorch

Source of truth in the file: `TORCH_META` (companion versions) and
`CUDA_TORCH_COMBINATIONS` (one row per CUDA base x torch). Our CUDA bases are
**12.8.1, 12.9.0, 13.0.0, 13.2.0** (see `official-templates/shared/versions.hcl`).

Steps:
1. Find our highest torch in `TORCH_META`. Check PyPI (`torch` on pypi.org) and the
   PyTorch index for newer **stable** releases (ignore rc/dev/nightly). If none are
   newer, pytorch is current.
2. For each new stable torch version, add one `TORCH_META` entry with the matching
   companion versions, each verified to exist on the index you will pull it from:
   - `torchvision`: the release paired with that torch.
   - `torchaudio`: pinned to **2.11.0** (torchaudio's last release; dropped from the
     PyTorch release process after 2.11, upstream says it stays compatible).
   - `torchcodec`: the build that declares `torch >=` your version. torchcodec backs
     `torchaudio.load/save` from torch 2.9 on, so 2.9+ needs it.
3. For each of the four CUDA bases, add a `CUDA_TORCH_COMBINATIONS` row choosing
   `whl_src` = the `cuXXX` index that actually has a wheel for this torch. Verify by
   listing `https://download.pytorch.org/whl/cu<NNN>/torch/` and confirming the exact
   `torch-<version>+cu<NNN>` wheel is present. Rules the existing rows encode:
   - Prefer the newest `cuXXX` the base supports. Avoid `cu126` for new versions:
     it stops at sm_90 with no PTX, so it cannot run on Blackwell.
   - cu128 was deprecated in torch 2.12 and removed in 2.13. For 12.x bases on those
     versions use `cu129`.
   - For the **13.2.0** base, if no `cu132` torchaudio wheel exists (it usually does
     not, since torchaudio ended at 2.11.0 cu130), set `audio_index = "cpu"` on that
     row, matching the existing 13.2 rows.
   - If a given base has no working wheel for this torch, omit that row and list the
     gap in the PR body rather than inventing a `whl_src`.
4. Keep the comment style of the surrounding rows: a short note above any row that
   needs an explanation (unusual `whl_src`, `audio_index`, Blackwell caveat).
5. Update `official-templates/pytorch/README.md`: add the version to the
   "Available configurations" PyTorch line. Do not touch the "Available PyTorch
   Images" block, it is being removed. Only extend the prose notes (torchaudio,
   Blackwell) if the new version changes what they say; if it follows the same
   pattern, leave them.

## comfyui

Pins live at the top of `official-templates/comfyui/docker-bake.hcl`. **Do not**
touch `CUDA_TORCH_COMBINATIONS`: those torch pins are deliberately conservative
(see the long comment in the file), every ComfyUI release shares them, and each
row also carries `install_cuda_compat` and a `sageattention_*` wheel we build
ourselves — none of that tracks an upstream release.

⚠️ **Patched upstreams.** `patches/` is applied to the pinned ComfyUI core,
KJNodes, Civicomfy and RunpodDirect, and `manager-patches/` to the Manager, with
`git apply`, which refuses a patch whose context has moved. A pin bump that
touches patched code therefore **fails the build** rather than silently shipping
without the fix. That is the intended safety net, not something to work around:
never edit or delete a patch to make a bump apply. If a bump is in a PR, say in
the body that the patches still have to hold, and let CI prove it.

`COMFYUI_VERSIONS` is a list of `{ version, manager_version }`. Add a new stable
release tag (`vX.Y.Z`, keep the `v`) of `comfyanonymous/ComfyUI` **alongside** the
existing entries, never replacing them; the matrix fans it across the CUDA
variants on its own. `manager_version` is a pip pin that must match what that
ComfyUI release pins in its own `manager_requirements.txt` (the build asserts the
two agree) — read it from the release, do not guess, and do not reuse the
neighbouring entry's value.

Shared pins (one each, across all ComfyUI versions), 12-char short SHAs:
- `KJNODES_SHA`: latest default-branch commit of `kijai/ComfyUI-KJNodes`.
- `CIVICOMFY_SHA`: latest default-branch commit of `MoonGoblinDev/Civicomfy`.
- `RUNPODDIRECT_SHA`: latest default-branch commit of `MadiatorLabs/ComfyUI-RunpodDirect`.
- `FILEBROWSER_VERSION` / `FILEBROWSER_COMMIT`: leave both alone. Upstream
  `filebrowser/filebrowser` is archived (2026-09-01) and `v2.63.23` is its last
  release, so there is nothing to bump. The separate `filebrowser` family tracks
  the maintained fork instead.

If only some pins moved, bump just those.

The comfyui `README.md` does not spell out the ComfyUI, node, or filebrowser
version, so a pin bump usually needs no README change. The only version-bearing
part is the "Choosing a tag" table (torch x CUDA), which you are not changing.
Leave the README unless that table becomes wrong.

## autoresearch

Monitor **only `runpodctl`**. Everything else in autoresearch (Python deps, the
base image, and so on) is managed by hand; do not touch it.

`runpodctl` is pinned in `official-templates/autoresearch/Dockerfile`, not the
bake file:
- `RUNPODCTL_VERSION`: latest stable release tag (`vX.Y.Z`) of `runpod/runpodctl`.
- `RUNPODCTL_SHA256`: sha256 of that release's `runpodctl-linux-amd64.tar.gz`
  asset. Download it and compute the hash, do not guess.

This is a plain pin bump (not an add-alongside): replace both values. If
runpodctl is already current, do nothing. autoresearch has no version list in its
README, so no README change.

## base

Two things to monitor; everything else in base is managed by hand, do not touch it.

**get-pip**, pinned in `official-templates/base/Dockerfile`. `pypa/get-pip` is
tagged per pip version (tags like `26.2.2`); pin the commit the latest tag points
to, not an arbitrary branch tip.
- `GET_PIP_COMMIT`: the commit at the latest `pypa/get-pip` release tag. Annotate
  it with that version (`GET_PIP_COMMIT=... # 26.2.2`).
- `GET_PIP_SHA256`: sha256 of `public/get-pip.py` at that commit. Fetch the file
  and recompute the hash, do not guess. There is one hash: base installs pip for
  python3.11, 3.12 and 3.13 from this single script, all of which `public/` serves.

**nvidia/cuda** — **detection only, do not apply.** Adding a CUDA version is too
risky for now: `CUDA_VERSIONS` in `official-templates/shared/versions.hcl` is
shared by every family (base and autoresearch would start building it, pytorch
needs hand-written `CUDA_TORCH_COMBINATIONS` rows), so a human decides when to wire
it in. Still check Docker Hub for a `nvidia/cuda:<ver>-cudnn-devel-ubuntu*` tag of
a CUDA version newer than our highest (12.8.1, 12.9.0, 13.0.0, 13.2.0), on
**Ubuntu 24.04 or newer** — we no longer build 22.04 anywhere. An Ubuntu 26.04 one
is worth naming separately: `UBUNTU_VERSIONS` is 24.04 only because NVIDIA ships
no 26.04 image below CUDA 13.3, so the first 13.3+ tag is what unblocks adding
26.04 to the CUDA bases (the CPU base already builds it). If you find either, do
NOT edit `CUDA_VERSIONS`, `UBUNTU_VERSIONS`, the README, or anything else. Just
mark it: append a line to the Actions job summary
(`echo "..." >> "$GITHUB_STEP_SUMMARY"`) naming the new tag and that it was skipped
as too risky, and if a base PR is open for get-pip, note it there too.

A get-pip bump needs no README change (no version is listed there), and base makes
no other README change while CUDA is detection-only.

## pytorch-cluster

Monitoring daemons pinned in `official-templates/pytorch-cluster/Dockerfile`, each
a plain pin bump (replace the version and recompute the SHA-256 of the exact
asset, do not guess):
- `NODE_EXPORTER_VERSION` + `NODE_EXPORTER_SHA256`: latest release of
  `prometheus/node_exporter`, asset `node_exporter-<ver>.linux-amd64.tar.gz`.
- `PROMETHEUS_VERSION` + `PROMETHEUS_SHA256`: latest release of
  `prometheus/prometheus`, asset `prometheus-<ver>.linux-amd64.tar.gz`.
- `GRAFANA_VERSION` + `GRAFANA_BUILD` + `GRAFANA_SHA256`: latest Grafana OSS. The
  download URL carries a build id, so find the right `GRAFANA_BUILD` for the new
  version from dl.grafana.com and hash `grafana_<ver>_<build>_linux_amd64.tar.gz`.

dcgm-exporter is coupled across three ARGs and an apt pin, handle with care. The
image is assembled as
`nvcr.io/nvidia/k8s/dcgm-exporter:${DCGM_VERSION}-${DCGM_EXPORTER_VERSION}-distroless`,
and we lift only the exporter binary and the counter CSVs out of it; the DCGM
runtime it links against comes from apt in the same Dockerfile:
- `DCGM_EXPORTER_VERSION` is the exporter's own version, `DCGM_VERSION` the DCGM
  runtime it was built against. `DCGM_APT_VERSION` derives from `DCGM_VERSION`
  (`1:${DCGM_VERSION}-1`) and pins both `${DCGM_PACKAGE}` and
  `datacenter-gpu-manager-4-core`, so the exporter and the libdcgm it loads stay
  on the same version. Bump `DCGM_VERSION` only to a version that exists as that
  apt version, and only together with an exporter tag built against it — the two
  halves of the nvcr.io tag are not independent.
- Keep the **`-distroless`** suffix. Since 4.8.2 NVIDIA publishes only that
  flavour; do not reintroduce an `ubuntu*` suffix.
- `DCGM_PACKAGE` is **not** yours to bump: `docker-bake.hcl` sets it per matrix
  entry, deriving `datacenter-gpu-manager-4-cuda12` / `-cuda13` from the CUDA
  major. Leave the Dockerfile default alone.
- Only bump within the same DCGM major (4.x). A new major needs the
  `datacenter-gpu-manager-N` package family changed and the
  `/usr/bin/dcgm-exporter` and `/etc/dcgm-exporter` paths re-verified. Flag it in
  the PR body instead.
- When you do bump, repeat the Dockerfile's warning in the PR body: the exporter
  binary and `/etc/dcgm-exporter` contents must be re-verified, **and the release
  notes checked for label or metric renames** — the Grafana dashboards key off the
  `hostname` and `gpu` labels, and exporter 4.8.3 already renamed `Hostname` to
  `hostname` once.

This README lists no component versions, so no README change.

## ray-cluster

**Detection only, do not apply.** Every version in this family is locked to
something the scraper cannot re-derive:

- `RAY_VERSION` (`official-templates/ray-cluster/docker-bake.hcl`, mirrored by the
  Dockerfile's `ARG RAY_VERSION` default) is validated against parsers in a
  **different repo** — runpod/host's `pkg/rayready` and `pkg/raymetrics` — whose
  fixtures must be bumped with it. It also requires re-resolving
  `ray-cluster/requirements.txt`, which pins Ray's direct dependencies exactly
  (2.59.0 needs `aiohttp>=3.14.1`, for instance).
- `VLLM_VERSION` and `PYJWT_VERSION` (`ray-cluster/inference/Dockerfile`) require
  re-resolving `inference/requirements.txt` with the `uv pip compile` invocation
  written at the top of that file, against the base's torch and Ray.
- LiteLLM (`inference/litellm/requirements.in`, LTS line 1.108.x) is hash-pinned
  and must be re-locked with the `uv pip compile --generate-hashes` command in its
  header.

You have no `uv` in your allowed tools, so you cannot produce a correct lock file,
and a bump without one ships whatever the ranges happen to resolve to. So: check
`ray-project/ray` and `vllm-project/vllm` for releases newer than ours, and if you
find any, change nothing. Append a line to the Actions job summary
(`echo "..." >> "$GITHUB_STEP_SUMMARY"`) naming the new versions and that they need
a hand-resolved lock file plus, for Ray, the runpod/host fixtures. Open no PR.

## filebrowser

Its own family, separate from the FileBrowser that ships inside comfyui: this one
tracks **FileBrowser Quantum** (`gtsteffaniak/filebrowser`), the maintained fork.

`FILEBROWSER_VERSIONS` in `official-templates/filebrowser/docker-bake.hcl` is a
list of `{ version, sha256 }`. Add the new release **alongside** the existing
entries, never replacing them; the matrix fans each version across the CPU and
CUDA variants on its own.
- `version`: the GitHub release tag exactly as upstream writes it, including the
  suffix (`v2.0.1-stable`), since it goes into the image tag.
- `sha256`: of that release's **`linux-amd64-filebrowser`** asset — the bare
  binary, not a tarball. Download it and compute the hash, do not guess.

Do not touch `FILEBROWSER_CUDA`: it names the one CUDA variant built alongside the
CPU image and must stay a 24.04 CUDA build that runpod/base publishes
(`shared/versions.hcl`). The README names no version, so no README change.

## k3s-node

Three pins in `official-templates/k3s-node/docker-bake.hcl`. The image is built
for **amd64 and arm64**, so the binary pins need a checksum per architecture, and
those checksums sit in the target's `args` block rather than in `variable`s.

- `K3S_VERSION` (`v1.37.1+k3s1`) plus the `K3S_SHA256_AMD64` / `K3S_SHA256_ARM64`
  args. The release assets are `k3s` (amd64) and `k3s-arm64` (arm64); upstream
  publishes their checksums as `sha256sum-amd64.txt` and `sha256sum-arm64.txt` on
  the same release. Take both from there, or download both binaries and hash them.
  Keep the `+k3s1` build suffix, the tag strips it on its own.
  **Patch bumps only** (`v1.37.1+k3s1` -> `v1.37.2+k3s1`). A new Kubernetes minor
  changes which control planes this agent can join, so flag it in the job summary
  and leave the pin alone.
- `RUNC_VERSION` plus `RUNC_SHA256_AMD64` / `RUNC_SHA256_ARM64`, assets
  `runc.amd64` and `runc.arm64` from `opencontainers/runc`. This pin is a
  **temporary swap**: k3s bundles a runc below our security minimum, and
  `k3s-node.sh` replaces it at runtime. When you bump `K3S_VERSION`, check the
  "Runc" row of the k3s release notes — once a k3s release bundles runc >= the
  version pinned here, the whole swap should be deleted (the ARGs, the download,
  and the swap in `k3s-node.sh`). **Do not do that deletion yourself**; say in the
  PR body that the swap has become removable.
- `NVIDIA_CTK_VERSION` is an **apt package version** (`1.20.1-1`), not a release
  tag, and pins four packages at once (`nvidia-container-toolkit`, `-base`,
  `libnvidia-container-tools`, `libnvidia-container1`). Only bump to a version all
  four carry in NVIDIA's `libnvidia-container/stable/deb` repo.

The README states "**runc 1.4.3**, in place of the 1.4.2 that this k3s release
bundles" — update both numbers whenever the runc pin or the k3s release moves.

## sandbox-ubuntu

Base image for the other sandboxes. Four pins, each a plain bump:
- **Ubuntu digest**: `BASE_IMAGE = "ubuntu:26.04@sha256:..."` in
  `official-templates/sandbox-ubuntu/docker-bake.hcl`. Keep the `26.04` tag; if the
  tag's current Docker Hub digest differs from the pinned one, update the digest
  (`docker buildx imagetools inspect ubuntu:26.04`).
- **Node**: `NODE_VERSION` + `NODE_SHA256` in the Dockerfile. Latest Node 24 LTS
  from nodejs.org/dist, asset `node-v<ver>-linux-x64.tar.xz`. Stay on the 24 LTS
  line (the README says "Node.js 24 LTS").
- **tar deb**: `TAR_DEB` + `TAR_DEB_SHA256`. Newest `tar_*_amd64.deb` in
  `https://archive.ubuntu.com/ubuntu/pool/main/t/tar/`, download it and hash it.
- **uv**: `ghcr.io/astral-sh/uv:<ver>@sha256:...` in the Dockerfile COPY. Latest
  `astral-sh/uv` release; update both the version and the digest
  (`docker buildx imagetools inspect ghcr.io/astral-sh/uv:<ver>`).

The README states only majors (Ubuntu 26.04, Node 24, Python 3.14), so these bumps
need no README change unless a stated major/LTS line changes.

## sandbox-browser

`PLAYWRIGHT_VERSION`, one pin for both the npm and the pip install. It lives in
**two** places that must move together: the `variable "PLAYWRIGHT_VERSION"` in
`official-templates/sandbox-browser/docker-bake.hcl` (the authoritative one, it is
also in the image tag) and the `ARG PLAYWRIGHT_VERSION` default in the Dockerfile.
Bump to the latest Playwright release, verifying it exists on both npm
(`playwright`) and PyPI (`playwright`). Update the "Playwright X.Y.Z" line in the
README.

## sandbox-harbor

`HARBOR_VERSION`, installed via `uv tool install harbor==`. As with
sandbox-browser it lives in two places that must move together: the
`variable "HARBOR_VERSION"` in `official-templates/sandbox-harbor/docker-bake.hcl`
(authoritative, and in the image tag) and the `ARG HARBOR_VERSION` default in the
Dockerfile. Bump to the latest `harbor` release on PyPI. Update the
"Harbor X.Y.Z" line in the README.

## sandbox-openclaw

`OPENCLAW_VERSION` + `OPENCLAW_DIGEST` in
`official-templates/sandbox-openclaw/docker-bake.hcl` (image
`ghcr.io/openclaw/openclaw:<ver>@<digest>`). Bump to the latest openclaw release
tag and update the digest together
(`docker buildx imagetools inspect ghcr.io/openclaw/openclaw:<ver>`); the two must
stay in lockstep. Update the "OpenClaw <version>" line in the README.

## PR body

For each PR, state: what moved (old -> new) and, for each bump, a brief summary of
the notable changes between our current version and the new one (from the upstream
release notes or changelog, a few bullets, not a full dump), plus any risks for
users (breaking changes, deprecations, behavior shifts that could affect existing
pods or workflows); which inputs you
verified and how (the index URL, the computed checksum); and any CUDA base you
deliberately left out and why. End with: "Matrix and runtime correctness are
verified by the build and smoke-test CI on this PR."
