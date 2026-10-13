#!/usr/bin/env bash
# Checks a runpod/browser container from the inside. CI runs it under the
# default sandbox limits (see sandbox.yml); the same script can be copied into
# a real sandbox on dev and run through exec.
#
#   check.sh [OUT_DIR]        screenshots land in OUT_DIR (default /tmp/browser-check)
#
# Needs network access to example.com. PLAYWRIGHT_VERSION, when set, is the
# version both bindings must report.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-/tmp/browser-check}"
URL="https://example.com"
mkdir -p "$OUT"

# Every check also reports what it found: a green step that prints nothing
# tells the next person nothing.
say() { printf "  %-14s %s\n" "$1" "$2"; }

test "$(id -un)" = user
sudo -n true
say user "$(id -un) (uid $(id -u)), passwordless sudo"

# Recorded explicitly: a sandbox reporting other ids is the runtime shifting
# them, not this image. Real case: uid 655360 on dev.
test "$(stat -c %u /etc/sudo.conf)" = 0
test "$(stat -c %u /home/user)" = "$(id -u)"
say ownership "sudo.conf uid $(stat -c %u /etc/sudo.conf), /home/user uid $(stat -c %u /home/user)"

# Two bindings on different versions would each want their own Chromium,
# and only one is baked in.
PY_VERSION="$(python -c 'import importlib.metadata as m; print(m.version("playwright"))')"
NODE_VERSION="$(npm ls --global --json playwright | jq -r '.dependencies.playwright.version')"
test "$PY_VERSION" = "$NODE_VERSION"
test -z "${PLAYWRIGHT_VERSION:-}" || test "$PY_VERSION" = "$PLAYWRIGHT_VERSION"
say playwright "python $PY_VERSION, node $NODE_VERSION"

# Exactly one Chromium build, and the user cannot remove it.
mapfile -t BUILDS < <(find "$PLAYWRIGHT_BROWSERS_PATH" -mindepth 1 -maxdepth 1 -name 'chromium-*')
test "${#BUILDS[@]}" = 1
test ! -w "$PLAYWRIGHT_BROWSERS_PATH"
say chromium "$(basename "${BUILDS[0]}") in $PLAYWRIGHT_BROWSERS_PATH, read-only"

# /dev/shm is whatever the runtime gives it (64 MB under plain Docker).
# Playwright passes --disable-dev-shm-usage, so that must be enough.
say shm "$(df -h /dev/shm | awk 'NR==2 {print $2}')"

python "$HERE/browser_check.py" screenshot "$URL" "$OUT/python.png" > /dev/null
say python "$(python "$HERE/browser_check.py" png "$OUT/python.png")"

# Run from a directory with no node_modules of its own, so resolution has to
# reach the global install.
(cd /tmp && node "$HERE/browser_check.mjs" "$URL" "$OUT/node-esm.png" > /dev/null)
(cd /tmp && node "$HERE/browser_check.cjs" "$URL" "$OUT/node-cjs.png" > /dev/null)
say node-esm "$(python "$HERE/browser_check.py" png "$OUT/node-esm.png")"
say node-cjs "$(python "$HERE/browser_check.py" png "$OUT/node-cjs.png")"

# From inside a virtualenv: the launcher must keep using the system
# interpreter Playwright is installed into, not the venv's.
uv venv --quiet /tmp/browser-check-venv
# shellcheck source=/dev/null
(source /tmp/browser-check-venv/bin/activate &&
  playwright screenshot "$URL" "$OUT/cli.png" > /dev/null)
say cli "$(python "$HERE/browser_check.py" png "$OUT/cli.png"), from inside a venv"

echo "  fonts"
python "$HERE/browser_check.py" fonts "$OUT/cjk-emoji.png"
say fonts "$(python "$HERE/browser_check.py" png "$OUT/cjk-emoji.png"), no fallback glyphs"

# cgroup v2 records the high-water mark for the whole container, which is
# what an OOM kill would have been judged against.
if [ -r /sys/fs/cgroup/memory.peak ]; then
  LIMIT="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)"
  [ "$LIMIT" = max ] || LIMIT="$(( LIMIT / 1048576 )) MiB"
  say memory "peak $(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 )) MiB, limit $LIMIT"
fi
