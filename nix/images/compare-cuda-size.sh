#!/usr/bin/env bash
# Build-only comparison for the HYBRID CUDA image (nvidia/cuda base + Nix
# userland) vs the published runpod CUDA chain. No image is pushed.
#
# Usage: nix/images/compare-cuda-size.sh
# Needs on PATH: nix, gzip, wc; skopeo + jq reachable via `nix run nixpkgs#...`.
set -euo pipefail

SYSTEM="x86_64-linux"
NVIDIA_REF="docker://docker.io/nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04"
BASE_REF="docker://docker.io/runpod/base:1.0.7-cuda1281-ubuntu2404"
PYTORCH_REF="docker://docker.io/runpod/pytorch:1.0.7-cu1281-torch280-ubuntu2404"

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
mb() { echo $(($1 / 1048576)); }

# Compressed download size (amd64) of a published image, via skopeo (no pull).
compressed_mb() {
  local ref="$1" raw
  export CONTAINERS_REGISTRIES_CONF="${CONTAINERS_REGISTRIES_CONF:-/dev/null}"
  if raw=$(nixf run nixpkgs#skopeo -- inspect --override-os linux --override-arch amd64 "$ref" 2>/dev/null); then
    printf '%s' "$raw" | nixf run nixpkgs#jq -- -r '[.LayersData[].Size] | add' 2>/dev/null || echo ""
  else
    echo ""
  fi
}

echo "==> building hybrid base-cuda image (pulls pinned nvidia base; build-only)"
nixf build ".#packages.${SYSTEM}.base-cuda" -o result-base-cuda-image

echo "==> measuring hybrid image (streaming ~6 GB, please wait)"
# gzip -6 (registry-default-ish) — -9 on an ~11 GB stream is far too slow.
raw=$(./result-base-cuda-image | wc -c)
gz=$(./result-base-cuda-image | gzip -6 | wc -c)

echo "==> fetching published baseline sizes (skopeo, no pull)"
nvidia_c=$(compressed_mb "$NVIDIA_REF")
base_c=$(compressed_mb "$BASE_REF")
pt_c=$(compressed_mb "$PYTORCH_REF")

emit() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >>"$GITHUB_STEP_SUMMARY"
  fi
}

emit ""
emit "## Hybrid CUDA image — build-only size comparison"
emit ""
emit "Hybrid = pinned \`nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04\` (fromImage) + the Nix userland. Torch is pip-installed identically on top of both the hybrid and runpod/base, so it is excluded here — this compares the **userland layer**."
emit ""
emit "| image | compressed (download) | uncompressed |"
emit "| --- | --- | --- |"
emit "| **hybrid base-cuda** (nvidia base + Nix userland) | $(mb "$gz") MB | $(mb "$raw") MB |"
[ -n "$base_c" ] && emit "| runpod/base:1.0.7-cuda1281-ubuntu2404 (nvidia base + apt userland) | $(mb "$base_c") MB | — |"
[ -n "$nvidia_c" ] && emit "| nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 (shared base) | $(mb "$nvidia_c") MB | — |"
[ -n "$pt_c" ] && emit "| runpod/pytorch:1.0.7-cu1281-torch280 (base + torch wheels) | $(mb "$pt_c") MB | — |"
emit ""
if [ -n "$base_c" ] && [ -n "$nvidia_c" ]; then
  nix_layer=$((gz - nvidia_c))
  apt_layer=$((base_c - nvidia_c))
  emit "**Userland layer added on top of the shared CUDA base:**"
  emit "- Nix: ~$(mb "$nix_layer") MB"
  emit "- apt (5 pythons + build tooling): ~$(mb "$apt_layer") MB"
  if [ "$apt_layer" -gt 0 ]; then
    emit ""
    emit "The Nix userland layer is **$((100 - nix_layer * 100 / apt_layer))% smaller** than the apt layer, cutting the base image from $(mb "$base_c") MB to $(mb "$gz") MB. The shared CUDA base ($(mb "$nvidia_c") MB) and torch wheels dominate the total, so the whole-image win is modest — the big further levers are a runtime (non-devel) base and a Nix-built torch."
  fi
fi
emit ""
emit "_Determinism holds as in the CPU image (streamLayeredImage zeroes timestamps); base pinned by digest + Nix hash. See nix/images/README.md._"
