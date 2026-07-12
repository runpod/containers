#!/usr/bin/env bash
# Cross-image layer-sharing "footprint" for the Nix image family, measured on
# the ACTUAL OCI layers each image emits (not the Nix closure). This matters:
# streamLayeredImage gives the top `maxLayers` store paths their own layer and
# bundles the rest into a single per-image "customisation layer" whose digest
# differs between images — so store-path sharing overstates real OCI sharing.
#
# For each image we stream the docker-archive, read its real layer digests +
# sizes via `skopeo inspect`, and dedupe by digest across the family. That is
# exactly what a host's Docker layer cache dedupes.
#
# Usage: nix/images/footprint.sh
set -euo pipefail

SYSTEM="x86_64-linux"
FAMILY=(family-base family-data family-serve)
export CONTAINERS_REGISTRIES_CONF="${CONTAINERS_REGISTRIES_CONF:-/dev/null}"

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
sk() { nixf run nixpkgs#skopeo -- "$@"; }
jqr() { nixf run nixpkgs#jq -- "$@"; }
mb() { echo "$(($1 / 1048576))"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
: >"$tmp/all.tsv"

emit() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >>"$GITHUB_STEP_SUMMARY"
  fi
}

emit ""
emit "## Nix image family — real OCI layer-sharing footprint"
emit ""
emit "| image | OCI layers | size |"
emit "| --- | --- | --- |"
for img in "${FAMILY[@]}"; do
  echo "==> building + inspecting: $img" >&2
  out=$(nixf build --no-link --print-out-paths ".#packages.${SYSTEM}.$img")
  "$out" >"$tmp/img.tar"
  sk inspect "docker-archive:$tmp/img.tar" \
    | jqr -r '.LayersData[] | "\(.Digest)\t\(.Size)"' >"$tmp/$img.layers"
  rm -f "$tmp/img.tar"
  nlayers=$(wc -l <"$tmp/$img.layers")
  total=$(awk -F'\t' '{s += $2} END {print s}' "$tmp/$img.layers")
  cat "$tmp/$img.layers" >>"$tmp/all.tsv"
  emit "| \`$img\` | $nlayers | $(mb "$total") MB |"
done

naive=$(awk -F'\t' '{s += $2} END {print s}' "$tmp/all.tsv")
unique=$(sort -u -k1,1 "$tmp/all.tsv" | awk -F'\t' '{s += $2} END {print s}')
saved=$((naive - unique))
total_layers=$(wc -l <"$tmp/all.tsv")
unique_layers=$(sort -u -k1,1 "$tmp/all.tsv" | wc -l)

emit ""
emit "- **Naïve sum** (every image, no sharing): $(mb "$naive") MB"
emit "- **Unique cached on a host** (OCI layers deduped by digest): $(mb "$unique") MB"
emit "- **Saved by sharing:** $(mb "$saved") MB — $((saved * 100 / naive))% of the naïve total"
emit "- Layers: $total_layers total across the family, $unique_layers unique digests"
emit ""
emit "_Real OCI layer blobs (via \`skopeo inspect docker-archive:\`), deduped by digest — what a host's Docker cache actually shares. streamLayeredImage bundles the store paths beyond \`maxLayers\` into a per-image customisation layer, so this is below the store-path ceiling; raising maxLayers or using nix2container trades layer count for more sharing (see README)._"
