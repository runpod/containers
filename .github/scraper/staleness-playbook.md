# Template staleness playbook

Instructions for the weekly staleness scraper (`.github/workflows/staleness-scraper.yml`).
You are running headless in GitHub Actions. Your job: find upstream releases we do
not yet ship, and, where you can verify the build inputs exist, open a draft PR that
adds them following the exact conventions already in the repo.

Covered families: **pytorch**, **comfyui**. Ignore all others for now.

## Ground rules

- Edit the family's `docker-bake.hcl` and its `README.md`. The README version
  lists are hand-maintained (the `update-readme` action only pushes README.md to
  the Runpod template API, it does not generate them), so a new version must be
  added there too. See the README notes in each family section below.
- Never replace a supported version with a newer one. Add the new version
  **alongside** the existing ones and leave the old entries untouched. We keep
  shipping the old versions; the scraper only ever adds.
- When you bump a pin that is a git commit SHA, always add a short trailing
  comment. Use the version when the commit maps to a release tag
  (`FOO_SHA = "abc123..." # v1.2.3`); when it is untagged, use the commit date
  instead (`FOO_SHA = "abc123..." # 2026-10-20`).
- When you cannot verify that a build input (a wheel, a release asset, a checksum)
  actually exists, do NOT guess it in. Leave it out and say so in the PR body.
  The CUDA/wheel matrix is hand-curated, a wrong pin fails the build.
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

Pins live at the top of `official-templates/comfyui/docker-bake.hcl`. Read the live
file first, its shape is changing (PR #182 turns the single version into a list and
moves the Manager to a pip pin). **Do not** touch `CUDA_TORCH_COMBINATIONS`, those
torch pins are deliberately conservative (see the long comment in the file); every
ComfyUI release shares them.

ComfyUI release, add the new one **alongside** the existing ones, never replace:
- If the file has a `COMFYUI_VERSIONS` list (post-#182), append the new stable
  release tag (`vX.Y.Z`, keep the `v`) of `comfyanonymous/ComfyUI`, keeping the
  old entries. The matrix fans it across the CUDA variants on its own.
- If it still has a single `COMFYUI_VERSION` (pre-#182), the structure cannot hold
  two versions yet. Do not replace it. Just flag the new release in the PR body and
  bump only the shared node/filebrowser pins below.

Manager:
- Post-#182: `MANAGER_VERSION` is a pip pin that must match what the added ComfyUI
  release pins in its `manager_requirements.txt` (the build asserts they agree).
  Set it to that version, do not guess.
- Pre-#182: `MANAGER_SHA`, latest default-branch commit of `ltdrdata/ComfyUI-Manager`.

Shared pins (one each, across all ComfyUI versions), 12-char short SHAs:
- `KJNODES_SHA`: latest default-branch commit of `kijai/ComfyUI-KJNodes`.
- `CIVICOMFY_SHA`: latest default-branch commit of `MoonGoblinDev/Civicomfy`.
- `RUNPODDIRECT_SHA`: latest default-branch commit of `MadiatorLabs/ComfyUI-RunpodDirect`.
- `FILEBROWSER_VERSION`: latest release tag (`vX.Y.Z`) of `filebrowser/filebrowser`.
- `FILEBROWSER_SHA256`: sha256 of that release's `linux-amd64-filebrowser.tar.gz`
  asset. Download it and compute the hash, do not guess.

If only some pins moved, bump just those.

The comfyui `README.md` does not spell out the ComfyUI, node, or filebrowser
version, so a pin bump usually needs no README change. The only version-bearing
part is the "Choosing a tag" table (torch x CUDA), which you are not changing.
Leave the README unless that table becomes wrong.

## PR body

For each PR, state: what moved (old -> new), which inputs you verified and how
(the index URL, the computed checksum), and any CUDA base you deliberately left out
and why. End with: "Matrix and runtime correctness are verified by the build and
smoke-test CI on this PR."
