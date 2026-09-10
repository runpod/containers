#!/usr/bin/env bash
# fetch-hashes.sh — Query GitHub for latest custom node commit SHAs.
# Prints HCL-formatted output for copy-paste into docker-bake.hcl.
#
# Usage:
#   ./scripts/fetch-hashes.sh
#   GITHUB_TOKEN=ghp_xxx ./scripts/fetch-hashes.sh  # higher rate limit
#
# Works on both Linux (bash 4+) and macOS (bash 3.2).

set -euo pipefail

NODES="
ltdrdata/ComfyUI-Manager|MANAGER_SHA
kijai/ComfyUI-KJNodes|KJNODES_SHA
MoonGoblinDev/Civicomfy|CIVICOMFY_SHA
MadiatorLabs/ComfyUI-RunpodDirect|RUNPODDIRECT_SHA
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

fetch_latest_sha() {
  local repo="$1"
  local response
  local auth_header=""
  [[ -n "${GITHUB_TOKEN:-}" ]] && auth_header="Authorization: Bearer $GITHUB_TOKEN"

  if [[ -n "$auth_header" ]]; then
    response=$(curl -fsSL -H "$auth_header" \
      -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/${repo}/commits?per_page=1" 2>/dev/null) || { echo "ERROR"; return; }
  else
    response=$(curl -fsSL \
      -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/${repo}/commits?per_page=1" 2>/dev/null) || { echo "ERROR"; return; }
  fi
  echo "$response" | sed -n 's/.*"sha" *: *"\([a-f0-9]\{12\}\).*/\1/p' | head -1
}

echo "# Updated custom node hashes ($(date +%Y-%m-%d))"
echo "# Paste these into docker-bake.hcl to update"
echo ""

while IFS='|' read -r repo var_name; do
  [[ -z "$repo" ]] && continue

  current=$(get_current_hash "$var_name")
  latest=$(fetch_latest_sha "$repo")

  if [[ "$latest" == "ERROR" ]]; then
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
  echo "variable \"${var_name}\" {"
  echo "  default = \"${latest}\""
  echo "}"
done <<< "$NODES"

echo ""
echo "# ^ Copy the variable blocks above into docker-bake.hcl"
