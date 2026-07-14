#!/usr/bin/env bash
# Fleet-wide layer-sharing footprint of the *published* runpod images (all
# container types). Measures how much a host that ran the whole fleet would
# cache once shared Docker layers dedupe (unique blob digests) vs the naïve sum
# of every image — i.e. how much layer sharing the current Dockerfile fleet
# already achieves, and how much is still duplicated.
#
# Read-only: uses `skopeo inspect` (manifests only, no blob pulls). Anonymous
# Docker Hub manifest requests are rate-limited (~100/6h/IP); set
# DOCKERHUB_USERNAME + DOCKERHUB_TOKEN to authenticate and avoid throttling.
#
# Usage: nix/images/fleet-footprint.sh
set -euo pipefail

REPOS=(base pytorch autoresearch nvidia-pytorch)
VER="1.0.7"
export CONTAINERS_REGISTRIES_CONF="${CONTAINERS_REGISTRIES_CONF:-/dev/null}"

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
sk() { nixf run nixpkgs#skopeo -- "$@"; }
jqr() { nixf run nixpkgs#jq -- "$@"; }
gb() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1073741824 }'; }

creds=()
if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
  creds=(--creds "${DOCKERHUB_USERNAME}:${DOCKERHUB_TOKEN}")
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
: >"$tmp/layers.tsv" # digest \t size  (one line per layer occurrence)
: >"$tmp/images.tsv" # repo \t ref \t imgsize

emit() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >>"$GITHUB_STEP_SUMMARY"
  fi
}

for repo in "${REPOS[@]}"; do
  tags=$(sk "${creds[@]}" list-tags "docker://docker.io/runpod/$repo" \
    | jqr -r '.Tags[]' | grep -E "^${VER}-" | grep -vE -- '-dev-|-rc\.' || true)
  for t in $tags; do
    ref="docker://docker.io/runpod/$repo:$t"
    if ! j=$(sk "${creds[@]}" inspect --override-os linux --override-arch amd64 "$ref" 2>/dev/null); then
      echo "  skip (inspect failed / rate-limited): runpod/$repo:$t" >&2
      continue
    fi
    echo "$j" | jqr -r '.LayersData[] | "\(.Digest)\t\(.Size)"' >>"$tmp/layers.tsv"
    isize=$(echo "$j" | jqr -r '[.LayersData[].Size] | add')
    printf '%s\t%s\t%s\n' "$repo" "runpod/$repo:$t" "$isize" >>"$tmp/images.tsv"
  done
done

n=$(wc -l <"$tmp/images.tsv")
naive=$(awk -F'\t' '{s += $3} END {print s}' "$tmp/images.tsv")
unique=$(sort -u -k1,1 "$tmp/layers.tsv" | awk -F'\t' '{s += $2} END {print s}')
saved=$((naive - unique))

emit ""
emit "## Published fleet — current layer-sharing footprint"
emit ""
emit "All \`$VER\` release images across every container type (compressed / download sizes, amd64, via skopeo)."
emit ""
emit "| container type | images | naïve sum |"
emit "| --- | --- | --- |"
for repo in "${REPOS[@]}"; do
  ri=$(awk -F'\t' -v r="$repo" '$1 == r {c++; s += $3} END {print c "\t" s}' "$tmp/images.tsv")
  emit "| runpod/$repo | $(echo "$ri" | cut -f1) | $(gb "$(echo "$ri" | cut -f2)") GB |"
done
emit ""
emit "- **Fleet images:** $n"
emit "- **Naïve sum** (every image, no sharing): **$(gb "$naive") GB**"
emit "- **Unique cached on a host** (shared layers deduped by digest): **$(gb "$unique") GB**"
emit "- **Already shared by the current images:** $(gb "$saved") GB — $((saved * 100 / naive))% of the naïve total"
emit ""
emit "_The Dockerfile fleet already dedupes its common \`FROM\` layers (nvidia/cuda + runpod/base). Nix's additional lever is the userland tier (smaller + deterministic) and finer, guaranteed store-path sharing — see the family footprint above._"
