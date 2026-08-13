#!/usr/bin/env bash
# Detect the Conventional Commits bump level for a commit message or PR title+body.
#
# Type (feat/fix/perf/none) is taken from the SUBJECT (first line) only, so a
# squash-merge body that lists branch commits (`* feat: …`) cannot trigger a
# phantom bump. A major bump is either `type!:` in the subject or a properly
# formed git-trailer footer (`BREAKING CHANGE:` / `BREAKING-CHANGE:` at the
# start of a line). See https://www.conventionalcommits.org/en/v1.0.0/

detect_bump() {
  local text="$1"
  text="$(printf '%s' "$text" | tr -d '\r')"
  local subject="${text%%$'\n'*}"

  if printf '%s\n' "$subject" | grep -qiE '^[a-z]+(\([^)]*\))?!:'; then
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
