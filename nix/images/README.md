# Nix-built container images (experimental, build-only)

A proof-of-concept for building RunPod's container images with Nix
(`pkgs.dockerTools`) instead of Dockerfiles, to measure how much smaller and
more deterministic the result is. **Nothing here is published** — this is a
build + measure experiment only.

## TL;DR — measured on the CPU base

| image | compressed (download) | layers |
| --- | --- | --- |
| `runpod/base:1.0.7-ubuntu2404` (Dockerfile) | **714 MB** | 20 |
| `nix base-cpu` (this PoC, Python 3.14) | **295 MB** | ~98 |

≈ **59% smaller** compressed download. Numbers are reproduced on every CI run
by [`compare-size.sh`](./compare-size.sh) (job `image-size` in
`.github/workflows/nix.yml`).

**Fair-comparison caveat:** the published base bundles Python 3.9–3.13 plus a
large apt userland; this PoC ships a single Python (3.14) and a curated tool
set. Some of the win is "fewer Pythons," but the determinism, layer dedup, and
no-package-manager-in-the-image properties are structural and hold regardless.

## Hybrid CUDA image (`base-cuda.nix`)

The images people actually run are CUDA/PyTorch. Rather than rebuild CUDA in
Nix (unfree, huge, CI-fragile), the **hybrid** pins NVIDIA's tested CUDA base as
`fromImage` and layers the same Nix userland on top. Directly comparable to
`runpod/base:1.0.7-cuda1281-ubuntu2404`, which is the *same* nvidia base + an
apt userland layer. Torch is pip-installed identically on top of both, so it's
excluded — this compares the **userland layer**.

| image | compressed | note |
| --- | --- | --- |
| `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04` | 5593 MB | shared base |
| **hybrid base-cuda** (nvidia + Nix userland) | **5846 MB** | Nix layer ≈ **253 MB** |
| `runpod/base:1.0.7-cuda1281-ubuntu2404` (nvidia + apt) | 6359 MB | apt layer ≈ 766 MB |
| `runpod/pytorch:1.0.7-cu1281-torch280` (base + torch) | 11211 MB | torch ≈ +4.9 GB |

The Nix userland layer is **~67% smaller** than the apt layer (253 vs 766 MB).
But the shared CUDA base and torch wheels dominate, so the **whole-image** win
is modest (~8% on the base). The big further levers: a **runtime** (non-devel)
base, and a **Nix-built torch**. Reproduced by
[`compare-cuda-size.sh`](./compare-cuda-size.sh) (manual-dispatch CI job
`cuda-image-size` — heavy, so not run on every push). Base pinned by digest +
Nix hash via `nix-prefetch-docker`.

## Maximizing shared layers across an image family

These images co-deploy on the same hosts, so cross-image Docker layer reuse is
where the real fleet-level win is. Nix helps here in a way Dockerfiles cannot:

- **Automatic:** `dockerTools` layers are keyed by **store path**; an identical
  store path produces a byte-identical layer with an identical digest. So any
  two Nix images that share dependencies already share those layers in a host's
  Docker cache — pulled once, reused everywhere. `base-cpu` and `base-cuda` both
  `import ./userland.nix`, so their userland layers are literally the same
  digests today.
- **The subtlety:** `streamLayeredImage` assigns layers *per image* via a
  popularity heuristic capped at `maxLayers` (default 100); everything past the
  cap collapses into one "customisation layer." Two images with different
  closures can put a shared path in a dedicated (shared) layer in one and fold
  it into the customisation bundle of the other — so sharing is good but not
  guaranteed-maximal with naive independent builds.

**To force maximal, deterministic overlap** (proposed follow-up, not yet built):

1. **Tiered shared bases via `fromImage`.** Materialize the common closure once
   and chain: `common userland` → `+CUDA (per cuda version)` → `+torch (per
   combo)`. Every variant then reuses the exact lower-tier layer digests. (The
   CUDA hybrid already does the first hop off the nvidia base.)
2. **Raise `maxLayers`** so big shared deps (glibc, python, cudnn userland) each
   get a dedicated, dedupable layer instead of being bundled.
3. **`nix2container`** (`github:nlewo/nix2container`) is purpose-built for this:
   deterministic per-store-path layering designed so an image *family* shares
   layers maximally, without the single-customisation-layer collapse.
4. **Family "footprint" metric:** report total **unique** layer bytes a host
   caches for the whole family vs the naive sum of image sizes — that delta is
   the real co-location win, and a good CI guardrail against regressions.

## How it works

- **`base-cpu.nix`** — `pkgs.dockerTools.streamLayeredImage` assembling a
  Python 3.14 env (JupyterLab, notebook, ipywidgets, hf_transfer), `uv`,
  filebrowser, nginx, openssh and the common CLI tooling, plus the repo's
  `container-template/start.sh` and banner. `config.Cmd = ["/start.sh"]`.
- **`default.nix`** — registers the images; wired into the flake as
  `packages.<system>.base-cpu` (Linux only). `nix flake check` does **not**
  build it, so the fast gated-lint job is unaffected.
- **`compare-size.sh`** — builds the stream script, measures uncompressed +
  `gzip -9` size, verifies the stream is byte-identical across two runs
  (determinism), and fetches the published baseline's compressed size via
  `skopeo inspect --raw`.

Build and measure locally:

```sh
nix build .#packages.x86_64-linux.base-cpu -o result-image
./result-image | gzip -9 | wc -c          # compressed size
bash nix/images/compare-size.sh           # full comparison table
```

## Why Nix images (the structural wins)

- **Deterministic:** `streamLayeredImage` zeroes timestamps and derives content
  from the pinned `flake.lock`. Two builds → byte-identical tar (CI asserts
  this). No `apt-get update` drift, no "works on the build host" surprises.
- **Smaller:** only the exact runtime closure ships — no apt caches, no
  `build-essential`/`-dev` headers, no compilers, no package manager. Nothing
  is "installed then deleted in another layer."
- **Better layering / caching:** one store path per layer, content-addressed,
  so unrelated images that share (say) glibc or Python reuse the same layers on
  a host — big win across a family of images.
- **Auditable supply chain:** the full dependency graph is the Nix closure;
  `nix path-info -rS` gives an exact SBOM, and everything is pinned.

## Tradeoffs / open questions

- **Layer count:** ~98 fine-grained layers vs 20. Great for dedup, but some
  registries/pull paths prefer fewer layers — `maxLayers` is tunable.
- **`start.sh` assumes Debian:** it calls `service nginx/ssh start`. A Nix image
  has no sysvinit; a small entrypoint shim (or s6/supervisord) is needed for a
  runnable image. Out of scope for this size PoC.
- **Multi-Python parity:** adding 3.9–3.13 would grow the image (est.
  +150–250 MB) but should still beat the Dockerfile build.

## Path to GPU parity (not done here)

The images people actually run are CUDA/ROCm PyTorch. Options, in rough order of
effort:

1. **Hybrid** — keep the vendor CUDA/ROCm base image as `fromImage` and layer
   the Nix userland on top. Lowest risk, keeps NVIDIA's tested CUDA stack,
   still gets deterministic userland layers.
2. **Full Nix** — `python3Packages.torch` with `cudaSupport = true` from
   `cudaPackages`. Fully reproducible but unfree, very large closures, and a
   heavier CI build; needs validation against the current images.

Recommended next step: prototype option 1 for one CUDA PyTorch tag and re-run
`compare-size.sh` against it.
