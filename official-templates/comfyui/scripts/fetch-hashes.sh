#!/usr/bin/env bash
# fetch-hashes.sh — Query GitHub for the custom node commit SHAs to pin.
# Prints HCL-formatted output for copy-paste into docker-bake.hcl.
#
# Usage:
#   ./scripts/fetch-hashes.sh
#   GITHUB_TOKEN=ghp_xxx ./scripts/fetch-hashes.sh  # higher rate limit
#
# Works on both Linux (bash 4+) and macOS (bash 3.2).

set -euo pipefail

# ComfyUI-Manager is not here: it is installed from PyPI at the version ComfyUI
# pins in manager_requirements.txt, so it moves with COMFYUI_VERSION.
NODES="
kijai/ComfyUI-KJNodes|KJNODES_SHA
MoonGoblinDev/Civicomfy|CIVICOMFY_SHA
Madiator2011Work/ComfyUI-RunpodDirect|RUNPODDIRECT_SHA|release
"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BAKE_FILE="$SCRIPT_DIR/../docker-bake.hcl"

if [[ ! -f "$BAKE_FILE" ]]; then
  echo "ERROR: docker-bake.hcl not found at $BAKE_FILE" >&2
  exit 1
fi

get_current_hash() {
  local var_name="$1"
  grep -A2 "variable \"${var_name}\"" "$BAKE_FILE" | sed -n 's/.*default *= *"\([^"]*\)".*/\1/p' | head -1 || echo "unknown"
}

github_api() {
  local path="$1"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" \
      -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/${path}" 2>/dev/null
  else
    curl -fsSL \
      -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/${path}" 2>/dev/null
  fi
}

fetch_latest_sha() {
  local repo="$1"
  local response
  response=$(github_api "${repo}/commits?per_page=1") || { echo "ERROR"; return; }
  echo "$response" | sed -n 's/.*"sha" *: *"\([a-f0-9]\{12\}\).*/\1/p' | head -1
}

fetch_latest_release_tag() {
  local repo="$1"
  local response
  response=$(github_api "${repo}/releases/latest") || { echo "ERROR"; return; }
  echo "$response" | sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -1
}

fetch_tag_sha() {
  local repo="$1" tag="$2"
  local response
  response=$(github_api "${repo}/commits/${tag}") || { echo "ERROR"; return; }
  echo "$response" | sed -n 's/.*"sha" *: *"\([a-f0-9]\{12\}\).*/\1/p' | head -1
}

echo "# Updated custom node hashes ($(date +%Y-%m-%d))"
echo "# Paste these into docker-bake.hcl to update"
echo ""

while IFS='|' read -r repo var_name pin; do
  [[ -z "$repo" ]] && continue

  current=$(get_current_hash "$var_name")
  tag=""
  if [[ "$pin" == "release" ]]; then
    tag=$(fetch_latest_release_tag "$repo")
    if [[ -z "$tag" || "$tag" == "ERROR" ]]; then
      latest="ERROR"
    else
      latest=$(fetch_tag_sha "$repo" "$tag")
    fi
  else
    latest=$(fetch_latest_sha "$repo")
  fi

  if [[ -z "$latest" || "$latest" == "ERROR" ]]; then
    echo "# ${var_name}: FAILED to fetch from ${repo}" >&2
    echo "variable \"${var_name}\" {"
    echo "  default = \"${current}\""
    echo "}"
    continue
  fi

  if [[ "$current" == "$latest" ]]; then
    echo "# ${var_name}: ${current} (unchanged)"
  else
    echo "# ${var_name}: ${current} -> ${latest} (CHANGED)"
  fi
  [[ -n "$tag" ]] && echo "# ${repo#*/} ${tag}"
  echo "variable \"${var_name}\" {"
  echo "  default = \"${latest}\""
  echo "}"
done <<< "$NODES"

echo ""
echo "# ^ Copy the variable blocks above into docker-bake.hcl"
