#!/usr/bin/env bash
# Cross-image layer-sharing footprint for the Nix image family, measured on the
# ACTUAL OCI layers each image emits (not the Nix closure), for BOTH builders:
#   - dockerTools.streamLayeredImage (family-*)      default maxLayers 100
#   - nix2container                  (family-*-n2c)  maxLayers 600
#
# Why real OCI layers: streamLayeredImage bundles the store paths beyond
# maxLayers into a single per-image customisation layer with a distinct digest,
# so store-path sharing overstates OCI sharing. We stream each image to a
# docker-archive, read real layer digests + sizes via `skopeo inspect`, and
# dedupe by digest across the family — what a host's Docker cache shares.
#
# Usage: nix/images/footprint.sh
set -euo pipefail

SYSTEM="x86_64-linux"
export CONTAINERS_REGISTRIES_CONF="${CONTAINERS_REGISTRIES_CONF:-/dev/null}"

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
sk() { nixf run nixpkgs#skopeo -- "$@"; }
jqr() { nixf run nixpkgs#jq -- "$@"; }
mb() { echo "$(($1 / 1048576))"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

emit() {
  echo "$1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$1" >>"$GITHUB_STEP_SUMMARY"
  fi
}

# Patched skopeo that reads nix2container's `nix:` transport.
skn2c=""
for p in $(nixf build --no-link --print-out-paths ".#packages.${SYSTEM}.skopeo-n2c"); do
  [ -x "$p/bin/skopeo" ] && skn2c="$p/bin/skopeo" && break
done

layers_of() { # $1 = docker-archive path -> "digest\tsize" lines
  sk inspect "docker-archive:$1" | jqr -r '.LayersData[] | "\(.Digest)\t\(.Size)"'
}

# Measure one family. $1 = builder label, $2.. = image attr names.
# Streams each image to a docker-archive, collects real OCI layer digests+sizes.
measure_family() {
  local label="$1"
  shift
  local all="$tmp/$label.all.tsv"
  : >"$all"
  emit ""
  emit "### $label"
  emit ""
  emit "| image | OCI layers | size |"
  emit "| --- | --- | --- |"
  for img in "$@"; do
    echo "==> $label: $img" >&2
    local out
    out=$(nixf build --no-link --print-out-paths ".#packages.${SYSTEM}.$img")
    if [ "$label" = "nix2container" ]; then
      "$skn2c" --insecure-policy copy "nix:$out" "docker-archive:$tmp/img.tar:r:t" >/dev/null 2>&1
    else
      "$out" >"$tmp/img.tar"
    fi
    layers_of "$tmp/img.tar" >"$tmp/$img.layers"
    rm -f "$tmp/img.tar"
    cat "$tmp/$img.layers" >>"$all"
    emit "| \`$img\` | $(wc -l <"$tmp/$img.layers") | $(mb "$(awk -F'\t' '{s+=$2} END{print s}' "$tmp/$img.layers")") MB |"
  done
  local naive unique saved
  naive=$(awk -F'\t' '{s+=$2} END{print s}' "$all")
  unique=$(sort -u -k1,1 "$all" | awk -F'\t' '{s+=$2} END{print s}')
  saved=$((naive - unique))
  emit ""
  emit "- naïve sum: $(mb "$naive") MB · unique cached: $(mb "$unique") MB · **shared: $((saved * 100 / naive))%** ($(mb "$saved") MB)"
}

emit ""
emit "## Nix image family — real OCI layer-sharing footprint"

measure_family "dockerTools" family-base family-data family-serve
measure_family "nix2container" family-base-n2c family-data-n2c family-serve-n2c

emit ""
emit "_Real OCI layer blobs (\`skopeo inspect docker-archive:\`), deduped by digest. Both builders cap at the closure's store-path sharing ceiling (~53% here) only when every path is its own layer (~275+ layers/image); at its default (100) nix2container shares less than dockerTools. nix2container's edge is that many layers are cheap to build, plus explicit \`buildLayer\` composition — not a higher ceiling. See README._"
