#!/usr/bin/env bash
# List the commits in a range whose subject compute-version cannot read.
#
# main takes merge commits only, so a hotfix/* or revert-* PR is released from
# its own commit subjects, not from the PR title, and nothing can be reworded
# at merge time. A subject without a Conventional type (`Fix cuda path`)
# reads as bump none and the merge releases nothing. Matches what
# detect-bump.sh understands: `type:`, `type(scope):`, `type!:`, `Revert "`.

unconventional_subjects() {
  local range="$1"
  git log --no-merges --format='%h %s' "${range}" \
    | grep -viE '^[0-9a-f]+ ([a-z]+(\([^)]*\))?!?:|Revert ")' || true
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  unconventional_subjects "${1:?usage: commit-subjects.sh <revision-range>}"
fi
