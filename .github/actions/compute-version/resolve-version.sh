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

# git's empty tree, so a never-released family still gets a full range.
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Highest bump among the commits a family still has unreleased. A release can
# carry work from an earlier commit — a run that failed, or one GitHub dropped
# from the queue — and taking only HEAD's type would then ship a feature under
# a patch version.
BUMP_RANK_major=3
BUMP_RANK_minor=2
BUMP_RANK_patch=1
BUMP_RANK_none=0

max_bump() {
  local best="none" candidate rank_best rank_new
  for candidate in "$@"; do
    rank_best="BUMP_RANK_${best}"
    rank_new="BUMP_RANK_${candidate}"
    if [ "${!rank_new:-0}" -gt "${!rank_best:-0}" ]; then
      best="$candidate"
    fi
  done
  printf '%s\n' "$best"
}

# Walks `<since>..HEAD`, keeping only commits that touched one of the given
# pathspecs, and reduces their Conventional Commit types to one bump.
bump_for_range() {
  local since="$1"; shift
  local sha bumps=() message
  while IFS= read -r sha; do
    [ -z "$sha" ] && continue
    message="$(git log -1 --pretty=format:'%B' "$sha")"
    bumps+=("$(detect_bump "$message")")
  done < <(git log --format=%H "${since}..HEAD" -- "$@")
  [ "${#bumps[@]}" -eq 0 ] && { printf 'none\n'; return 0; }
  max_bump "${bumps[@]}"
}
