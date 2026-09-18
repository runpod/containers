#!/usr/bin/env bash
# Which release a commit sits on, and what the next version is.
#
# Git tags are the only state — nothing records released versions on the side.
# Each template family has its own series (`base-v1.3.1`, `comfyui-v1.4.0`);
# an empty prefix means the repo-wide `v1.3.1` series.

# Highest release tag of one series that HEAD sits on; empty when the series
# has no release yet. Two filters:
#   * tags ON HEAD are skipped, so re-running a push that was already tagged
#     bases off the previous release instead of its own tag;
#   * tags unreachable from HEAD are skipped, so re-running an older commit
#     after a newer release does not pick that newer, unrelated tag.
# Visited highest-version-first, so the first match is the answer.
latest_release_tag() {
  local prefix="${1:-}" head_sha tag
  head_sha="$(git rev-parse HEAD)"
  while IFS= read -r tag; do
    [ -z "$tag" ] && continue
    [ "$(git rev-list -n1 "$tag")" = "$head_sha" ] && continue
    git merge-base --is-ancestor "$tag" HEAD 2>/dev/null || continue
    printf '%s\n' "$tag"
    return 0
  done < <(git tag --list "${prefix}v[0-9]*.[0-9]*.[0-9]*" --sort=-v:refname)
}

# Where a family starts when it has never been released. The bump level is
# deliberately ignored for that first release — otherwise a `feat:` would
# publish 1.1.0 and 1.0.0 would never exist.
FIRST_VERSION="1.0.0"

next_version() {
  local base="${1:-}" bump="${2:-none}" major minor patch
  if [ -z "$base" ]; then
    printf '%s\n' "$FIRST_VERSION"
    return 0
  fi
  IFS='.' read -r major minor patch <<<"$base"
  major="${major:-0}"; minor="${minor:-0}"; patch="${patch:-0}"
  case "$bump" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    patch) patch=$((patch + 1)) ;;
  esac
  printf '%s.%s.%s\n' "$major" "$minor" "$patch"
}
