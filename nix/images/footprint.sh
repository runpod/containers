#!/usr/bin/env bash
# Cross-image layer-sharing "footprint": for the Nix image family, how many
# bytes does a host actually cache once shared layers are deduped, vs the naïve
# sum of each image's closure? The gap is the fleet-caching win.
#
# Metric = uncompressed store (NAR) bytes, which is what both the Nix store and
# Docker layer dedup key on (identical store path => identical layer => cached
# once). Compressed on-registry footprint is proportional.
#
# Usage: nix/images/footprint.sh
set -euo pipefail

SYSTEM="x86_64-linux"
FAMILY=(family-base family-data family-serve)

nixf() { nix --extra-experimental-features 'nix-command flakes' "$@"; }
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

# path\tnarSize for the full runtime closure of an image (its layer store paths
# and their deps). Handles both `nix path-info --json` shapes (array / object).
closure_tsv() {
  nixf path-info --json -r ".#packages.${SYSTEM}.$1" \
    | nixf run nixpkgs#jq -- -r \
      '(if type=="array" then . else (to_entries | map(.value + {path: .key})) end)
         | .[] | [.path, .narSize] | @tsv'
}

# path-info reports narSize only for realized paths, so build the family first
# (cheap: the stream scripts + substituting their closures from the cache).
echo "==> realizing family closures" >&2
nixf build --no-link "${FAMILY[@]/#/.#packages.${SYSTEM}.}"

emit ""
emit "## Nix image family — layer-sharing footprint"
emit ""
emit "| image | store closure (NAR) |"
emit "| --- | --- |"
for img in "${FAMILY[@]}"; do
  echo "==> realizing closure: $img" >&2
  closure_tsv "$img" >"$tmp/$img.tsv"
  total=$(awk -F'\t' '{s += $2} END {print s}' "$tmp/$img.tsv")
  cat "$tmp/$img.tsv" >>"$tmp/all.tsv"
  emit "| \`$img\` | $(mb "$total") MB |"
done

naive=$(awk -F'\t' '{s += $2} END {print s}' "$tmp/all.tsv")
unique=$(sort -u -k1,1 "$tmp/all.tsv" | awk -F'\t' '{s += $2} END {print s}')
saved=$((naive - unique))

emit ""
emit "- **Naïve sum** (if nothing were shared): $(mb "$naive") MB"
emit "- **Unique cached on a host** (shared layers deduped once): $(mb "$unique") MB"
emit "- **Saved by sharing:** $(mb "$saved") MB — $((saved * 100 / naive))% of the naïve total"
emit ""
emit "_Uncompressed store (NAR) bytes — what the Nix store and Docker layer dedup both key on. Identical store path ⇒ identical layer ⇒ cached once. Compressed on-registry footprint is proportional._"
