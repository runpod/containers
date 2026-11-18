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

# Highest release tag of one series, reachable or not; empty when the series
# has no release yet. For the dev env: releases are tagged on main's merge
# commits, which develop (and branches cut from it) never contain, so
# latest_release_tag would fall back to whatever predates the branch. Tags
# exist only on main, so the highest one is the last release. Tags ON HEAD
# are still skipped.
newest_release_tag() {
  local prefix="${1:-}" head_sha tag
  head_sha="$(git rev-parse HEAD)"
  while IFS= read -r tag; do
    [ -z "$tag" ] && continue
    [ "$(git rev-list -n1 "$tag")" = "$head_sha" ] && continue
    printf '%s\n' "$tag"
    return 0
  done < <(git tag --list "${prefix}v[0-9]*.[0-9]*.[0-9]*" --sort=-v:refname)
}

# Which set of Docker Hub repos an event publishes to: `prod` (the public
# `runpod/<repo>`) only for what targets the release branch — PRs into it and
# runs on it; `dev` (the private `runpod/<repo>-dev`) for everything else —
# develop, and also a PR from one feature branch into another, so nothing that
# is not headed for main can reach the public repos.
env_for() {
  local event="${1:-}" ref="${2:-}" base_ref="${3:-}" release_branch="${4:-main}"
  if [ "$event" = "pull_request" ]; then
    [ "$base_ref" = "$release_branch" ] && { printf 'prod\n'; return 0; }
  elif [ "$ref" = "refs/heads/${release_branch}" ]; then
    printf 'prod\n'
    return 0
  fi
  printf 'dev\n'
}

# PR number from a squash-merge subject, which GitHub ends with ` (#123)`;
# empty for anything else (a direct push, a merge commit's subject).
pr_from_subject() {
  local subject="${1:-}"
  if [[ "$subject" =~ \(#([0-9]+)\)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
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

bump_rank() {
  case "$1" in
    major) printf '3\n' ;;
    minor) printf '2\n' ;;
    patch) printf '1\n' ;;
    *)     printf '0\n' ;;
  esac
}

# Highest bump among the commits a family still has unreleased. A release can
# carry work from an earlier commit — a run that failed, or one GitHub dropped
# from the queue — and taking only HEAD's type would then ship a feature under
# a patch version.
max_bump() {
  local best="none" best_rank=0 candidate rank
  for candidate in "$@"; do
    rank="$(bump_rank "$candidate")"
    if [ "$rank" -gt "$best_rank" ]; then
      best="$candidate"
      best_rank="$rank"
    fi
  done
  printf '%s\n' "$best"
}

# Walks `<since>..HEAD`, keeping only commits that touched one of the given
# pathspecs, and reduces their Conventional Commit types to one bump. An empty
# `since` means the family has never been released, so everything counts.
bump_for_range() {
  local since="${1:-4b825dc642cb6eb9a060e54bf8d69288fbee4904}"; shift
  local sha bumps=() message
  while IFS= read -r sha; do
    [ -z "$sha" ] && continue
    message="$(git log -1 --pretty=format:'%B' "$sha")"
    bumps+=("$(detect_bump "$message")")
  done < <(git log --format=%H "${since}..HEAD" -- "$@")
  [ "${#bumps[@]}" -eq 0 ] && { printf 'none\n'; return 0; }
  max_bump "${bumps[@]}"
}
