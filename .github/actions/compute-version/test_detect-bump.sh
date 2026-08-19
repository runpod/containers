#!/usr/bin/env bash
# Unit tests for detect-bump.sh:
#   bash .github/actions/compute-version/test_detect-bump.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/detect-bump.sh"

FAILS=0

assert_bump() {
  local name="$1"
  local want="$2"
  local msg="$3"
  local got
  got="$(detect_bump "$msg")"
  if [ "$got" != "$want" ]; then
    echo "FAIL: ${name}: want ${want}, got ${got}"
    FAILS=$((FAILS + 1))
  else
    echo "PASS: ${name}"
  fi
}

assert_bump "feat subject is minor" minor $'feat: add comfyui template'
assert_bump "fix subject is patch" patch $'fix: correct cuda path'
assert_bump "ci subject is none" none $'ci: speed up build'
assert_bump "bang in subject is major" major $'feat!: drop ubuntu 20.04'
assert_bump "bang with scope is major" major $'fix(base)!: remove filebrowser'

assert_bump "BREAKING CHANGE footer is major even without bang" major $'feat: replace the image interface

BREAKING CHANGE: remove the previous interface'

assert_bump "BREAKING-CHANGE footer is major" major $'feat: replace the image interface

BREAKING-CHANGE: remove the previous interface'

assert_bump "body feat/fix lines do not bump" none $'ci: TEM-27 harden CI

* feat: upgrade filebrowser
* fix: cache-key
'

assert_bump "prose BREAKING CHANGE is not a footer" minor $'feat: add a warning

This commit mentions a BREAKING CHANGE in prose but is not a footer.
'

if [ "$FAILS" -ne 0 ]; then
  echo
  echo "${FAILS} test(s) failed"
  exit 1
fi

echo
echo "All detect-bump tests passed"
