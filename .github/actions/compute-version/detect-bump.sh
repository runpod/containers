#!/usr/bin/env bash
# Detect the Conventional Commits bump level for a commit message or PR title+body.
#
# feat/fix/perf/none come from the SUBJECT (first line) only, so squash-body
# lines like `* feat: …` cannot phantom-bump. A major bump is `type!:` in the
# subject, or a git-trailer footer `BREAKING CHANGE:` / `BREAKING-CHANGE:` at
# the start of a line. See https://www.conventionalcommits.org/en/v1.0.0/
#
# `Revert "<subject>"` (GitHub's Revert button, `git revert`) is a patch unless
# the reverted subject is a Conventional type that does not bump (docs:, ci:).
# main takes merge commits only, so a revert-* PR cannot be retitled at merge
# time: its commit subject is what this reads, and a none would leave the bad
# image the newest release. A reverted release reads `Revert "Merge pull
# request …"`, which has no type, so it is a patch too.

detect_bump() {
  local text="$1"
  text="$(printf '%s' "$text" | tr -d '\r')"
  local subject="${text%%$'\n'*}"
  local revert='^Revert "(.*)"$'

  if [[ "$subject" =~ $revert ]]; then
    local reverted="${BASH_REMATCH[1]}"
    if printf '%s\n' "$reverted" | grep -qiE '^[a-z]+(\([^)]*\))?!?:' \
      && [ "$(detect_bump "$reverted")" = "none" ]; then
      echo "none"
    else
      echo "patch"
    fi
  elif printf '%s\n' "$subject" | grep -qiE '^[a-z]+(\([^)]*\))?!:'; then
    echo "major"
  elif printf '%s\n' "$text" | grep -qE '^BREAKING[ -]CHANGE:'; then
    echo "major"
  elif printf '%s\n' "$subject" | grep -qiE '^feat(\([^)]*\))?:'; then
    echo "minor"
  elif printf '%s\n' "$subject" | grep -qiE '^(fix|perf)(\([^)]*\))?:'; then
    echo "patch"
  else
    echo "none"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  detect_bump "${1:?usage: detect-bump.sh <commit-message>}"
fi
