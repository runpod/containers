#!/usr/bin/env bash
# Unit tests for commit-subjects.sh:
#   bash .github/actions/check-pr-source/test_commit-subjects.sh
# Builds throwaway git repos in $TMPDIR — never touches the checkout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/commit-subjects.sh"

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

# A main with one release, and a hotfix branch off it.
new_repo() {
  local dir
  dir="$(mktemp -d)"
  cd "$dir"
  git init -q -b main
  git config user.email test@example.com
  git config user.name test
  commit "feat: initial"
  git checkout -q -b hotfix/x
}

subjects() {
  unconventional_subjects main..HEAD | cut -d' ' -f2-
}

new_repo
commit "fix: correct cuda path"
assert_eq "a fix commit passes" "" "$(subjects)"

new_repo
commit "fix(base)!: drop the old path"
commit "Fix: Capitalised type"
commit 'Revert "feat: add comfyui template (#12)"'
commit "ci: rerun the build"
assert_eq "scoped, breaking, capitalised, revert and ci pass" "" "$(subjects)"

new_repo
commit "Fix cuda path"
assert_eq "a subject without a type is listed" "Fix cuda path" "$(subjects)"

new_repo
commit "fix: correct cuda path"
commit "address review"
commit "fix:no space is still read"
assert_eq "only the bad one is listed" "address review" "$(subjects)"

new_repo
commit "fix: correct cuda path"
git checkout -q main
commit "feat: something on main"
git checkout -q hotfix/x
git merge -q --no-ff main -m "Merge branch 'main' into hotfix/x"
assert_eq "merge commits are skipped" "" "$(subjects)"

new_repo
assert_eq "an empty range lists nothing" "" "$(subjects)"

if [ "$FAILS" -ne 0 ]; then
  echo
  echo "${FAILS} test(s) failed"
  exit 1
fi

echo
echo "All commit-subjects tests passed"
