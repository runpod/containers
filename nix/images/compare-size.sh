#!/usr/bin/env bash
# Build-only comparison: the Nix-built base-cpu image vs the published
# runpod/base CPU image. Measures size + determinism and prints a table.
# No image is pushed anywhere.
#
# Usage: nix/images/compare-size.sh [baseline-tag]   (default 1.0.7-ubuntu2404)
# Needs on PATH: nix, gzip, sha256sum, wc; and (for the baseline) skopeo + jq
# reachable via `nix run nixpkgs#...`.
set -euo pipefail

BASELINE_TAG="${1:-1.0.7-ubuntu2404}"
BASELINE_REF="docker://docker.io/runpod/base:${BASELINE_TAG}"
SYSTEM="x86_64-linux"

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
mb() { echo $(($1 / 1048576)); }

echo "==> building Nix base-cpu image (stream script, build-only)"
nixf build ".#packages.${SYSTEM}.base-cpu" -o result-base-cpu-image

echo "==> measuring Nix image"
raw=$(./result-base-cpu-image | wc -c)
gz=$(./result-base-cpu-image | gzip -9 | wc -c)

echo "==> determinism check: stream twice, compare sha256"
h1=$(./result-base-cpu-image | sha256sum | cut -d' ' -f1)
h2=$(./result-base-cpu-image | sha256sum | cut -d' ' -f1)
if [ "$h1" = "$h2" ]; then
  det="identical (${h1:0:16}…)"
else
  det="DIFFERENT ($h1 vs $h2)"
fi

echo "==> baseline (compressed layer sizes via skopeo): $BASELINE_REF"
# Override any local (possibly v1) registries.conf so skopeo parses cleanly.
export CONTAINERS_REGISTRIES_CONF="${CONTAINERS_REGISTRIES_CONF:-/dev/null}"
base_c=""
if raw_manifest=$(nixf run nixpkgs#skopeo -- inspect --raw "$BASELINE_REF" 2>/dev/null); then
  base_c=$(printf '%s' "$raw_manifest" | nixf run nixpkgs#jq -- -r '[.layers[].size] | add' 2>/dev/null || echo "")
fi

emit() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >>"$GITHUB_STEP_SUMMARY"
  fi
}

emit ""
emit "## Nix base-cpu image — build-only size comparison"
emit ""
emit "| image | compressed (download) | uncompressed |"
emit "| --- | --- | --- |"
emit "| **nix base-cpu** (py3.14, single python) | $(mb "$gz") MB | $(mb "$raw") MB |"
if [ -n "$base_c" ]; then
  emit "| runpod/base:${BASELINE_TAG} (5 pythons) | $(mb "$base_c") MB | — |"
  emit ""
  emit "Compressed download is **$((100 - gz * 100 / base_c))% smaller** ($(mb "$gz") MB vs $(mb "$base_c") MB)."
else
  emit "| runpod/base:${BASELINE_TAG} | (manifest unavailable) | — |"
fi
emit ""
emit "Determinism (stream twice → sha256): **${det}**"
emit ""
emit "_Caveat: the published base ships Python 3.9–3.13 + a full apt userland; this PoC ships one Python (3.14). See nix/images/README.md._"
