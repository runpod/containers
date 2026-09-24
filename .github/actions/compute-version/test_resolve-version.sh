#!/usr/bin/env bash
# Unit tests for resolve-version.sh:
#   bash .github/actions/compute-version/test_resolve-version.sh
# Builds throwaway git repos in $TMPDIR — never touches the checkout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/detect-bump.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/resolve-version.sh"

FAILS=0

assert_eq() {
  local name="$1" want="$2" got="$3"
  if [ "$got" != "$want" ]; then
    echo "FAIL: ${name}: want '${want}', got '${got}'"
    FAILS=$((FAILS + 1))
  else
    echo "PASS: ${name}"
  fi
}

commit() {
  git commit -q --allow-empty -m "$1"
}

new_repo() {
  local dir
  dir="$(mktemp -d)"
  cd "$dir"
  git init -q .
  git config user.email ci@test
  git config user.name ci
  commit "feat: first"
}

# --- next_version ----------------------------------------------------------

assert_eq "minor bumps the middle field" 1.4.0 "$(next_version 1.3.1 minor)"
assert_eq "patch bumps the last field" 1.3.2 "$(next_version 1.3.1 patch)"
assert_eq "major zeroes the rest" 2.0.0 "$(next_version 1.3.1 major)"
assert_eq "none keeps the version" 1.3.1 "$(next_version 1.3.1 none)"
assert_eq "no release starts at 1.0.0" 1.0.0 "$(next_version "" minor)"
assert_eq "a first release ignores major" 1.0.0 "$(next_version "" major)"
assert_eq "a first release ignores none" 1.0.0 "$(next_version "" none)"

# --- latest_release_tag ----------------------------------------------------

new_repo
git tag v1.3.0
commit "fix: something"
git tag comfyui-v1.4.0
commit "fix: later"
assert_eq "unprefixed series ignores family tags" v1.3.0 "$(latest_release_tag "")"
assert_eq "family series ignores the shared tag" comfyui-v1.4.0 "$(latest_release_tag comfyui-)"
assert_eq "a family with no tag yet resolves empty" "" "$(latest_release_tag base-)"

new_repo
git tag base-v1.3.1
commit "feat: newer"
git tag base-v1.10.0
commit "fix: work on top of both"
assert_eq "10 sorts above 9, not lexically" base-v1.10.0 "$(latest_release_tag base-)"

# The tag on HEAD is the one release.yml just created; a re-run must base off
# the previous release so it recomputes the same version instead of bumping on
# top of its own tag.
new_repo
git tag base-v1.3.1
commit "feat: released by this very run"
git tag base-v1.4.0
assert_eq "the tag on HEAD is skipped" base-v1.3.1 "$(latest_release_tag base-)"

# Re-running an older commit must not pick up a release cut after it.
new_repo
git tag base-v1.3.1
OLD_HEAD="$(git rev-parse HEAD)"
commit "feat: later work"
git tag base-v1.4.0
git checkout -q "${OLD_HEAD}"
commit "fix: rebuild of the old commit"
assert_eq "unreachable newer tags are skipped" base-v1.3.1 "$(latest_release_tag base-)"

# --- max_bump / bump_for_range -------------------------------------------

assert_eq "major beats minor" major "$(max_bump minor major patch)"
assert_eq "minor beats patch" minor "$(max_bump patch none minor)"
assert_eq "nothing is none" none "$(max_bump)"

# A feature that arrived in an earlier commit must not ship as a patch just
# because the run happens to sit on a `fix:` commit.
new_repo
git tag base-v1.0.0
commit "feat: add a knob to the template"
mkdir -p t && echo x > t/f && git add t/f && commit "fix: correct the knob"
assert_eq "range takes the highest type" minor "$(bump_for_range base-v1.0.0)"
assert_eq "HEAD alone would say patch" patch "$(detect_bump "$(git log -1 --pretty=%B)")"

# Only commits touching the family's paths count.
new_repo
git tag base-v1.0.0
mkdir -p mine theirs
echo x > theirs/f && git add theirs/f && commit "feat: someone else's template"
echo x > mine/f && git add mine/f && commit "fix: my template"
assert_eq "other paths are ignored" patch "$(bump_for_range base-v1.0.0 mine/)"
assert_eq "no matching commits is none" none "$(bump_for_range base-v1.0.0 nothing/)"

if [ "$FAILS" -ne 0 ]; then
  echo
  echo "${FAILS} test(s) failed"
  exit 1
fi

echo
echo "All resolve-version tests passed"
