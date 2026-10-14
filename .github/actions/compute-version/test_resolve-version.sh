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

# --- newest_release_tag ----------------------------------------------------

# develop is merged into main with a merge commit, which is what gets tagged;
# develop then moves on without that commit in its history.
new_repo
git tag base-v1.0.0
git checkout -q -b develop
commit "feat: on develop"
git checkout -q -
git merge -q --no-ff -m "Merge develop" develop
git tag base-v1.1.0
git checkout -q develop
echo x > f && git add f && commit "fix: after the release"
assert_eq "the tagged merge is unreachable from develop" base-v1.0.0 \
  "$(latest_release_tag base-)"
assert_eq "newest_release_tag still finds it" base-v1.1.0 \
  "$(newest_release_tag base-)"
assert_eq "and only develop's new commits count since it" patch \
  "$(bump_for_range base-v1.1.0 .)"
assert_eq "a series with no tag resolves empty" "" "$(newest_release_tag comfyui-)"
git tag comfyui-v2.0.0
assert_eq "a tag on HEAD is skipped" "" "$(newest_release_tag comfyui-)"

# --- pr_from_subject -------------------------------------------------------

assert_eq "a squash subject names its PR" 42 "$(pr_from_subject "fix: CON-1 thing (#42)")"
assert_eq "a direct push has no PR" "" "$(pr_from_subject "fix: thing")"
assert_eq "a merge commit's subject is not read" "" \
  "$(pr_from_subject "Merge pull request #42 from runpod/feat/x")"
assert_eq "a #ref mid-subject is not the PR" "" \
  "$(pr_from_subject "fix: revert (#41) partially")"

# --- env_for -----------------------------------------------------------

assert_eq "PR into develop is dev" dev \
  "$(env_for pull_request refs/pull/7/merge develop)"
assert_eq "PR into main is prod" prod \
  "$(env_for pull_request refs/pull/7/merge main)"
assert_eq "PR between two feature branches is dev" dev \
  "$(env_for pull_request refs/pull/7/merge feat/base-branch)"
assert_eq "push to develop is dev" dev "$(env_for push refs/heads/develop "")"
assert_eq "push to main is prod" prod "$(env_for push refs/heads/main "")"
assert_eq "dispatch from main is prod" prod \
  "$(env_for workflow_dispatch refs/heads/main "")"
assert_eq "dispatch from develop is dev" dev \
  "$(env_for workflow_dispatch refs/heads/develop "")"
assert_eq "dispatch from a feature branch is dev" dev \
  "$(env_for workflow_dispatch refs/heads/feat/x "")"
assert_eq "a PR's ref does not count, only its base" dev \
  "$(env_for pull_request refs/heads/main develop)"
assert_eq "the release branch name is configurable" prod \
  "$(env_for push refs/heads/release "" release)"
assert_eq "a branch merely named like main is dev" dev \
  "$(env_for push refs/heads/feat/main "")"

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

# A base-only fix has to reach pytorch: the caller passes the dependency's
# paths along with the family's own, so the commit counts for both.
new_repo
git tag pytorch-v1.0.0
mkdir -p base pytorch
echo x > base/Dockerfile && git add base/Dockerfile && commit "fix: something in base"
assert_eq "a dependency's commit bumps the dependent" patch \
  "$(bump_for_range pytorch-v1.0.0 pytorch/ base/)"
assert_eq "without it the dependent would stall" none \
  "$(bump_for_range pytorch-v1.0.0 pytorch/)"

if [ "$FAILS" -ne 0 ]; then
  echo
  echo "${FAILS} test(s) failed"
  exit 1
fi

echo
echo "All resolve-version tests passed"
