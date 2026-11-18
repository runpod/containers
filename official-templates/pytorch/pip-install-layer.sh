#!/usr/bin/env bash
# pip install with a reproducible layer: every changed path gets LAYER_EPOCH
# as its time and .pyc files are compiled after that. Run with /tmp on tmpfs.
# Usage: pip-install-layer.sh [--dedupe-cuda] <pip install arguments>
set -euo pipefail

: "${LAYER_EPOCH:?set LAYER_EPOCH (seconds since 1970) for the file times}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dedupe=false
if [[ "${1:-}" == "--dedupe-cuda" ]]; then dedupe=true; shift; fi

stamp="$(mktemp)"
trap 'rm -f "${stamp}"' EXIT
# ctime: pip may keep wheel mtimes, but any change bumps ctime.
changed() {
  find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /tmp \) -prune \
    -o -cnewer "${stamp}" -print0
}
sleep 1

python -m pip install --no-compile "$@"
if [[ "${dedupe}" == true ]]; then python "${here}/dedupe-cuda-libs.py"; fi

changed | xargs -0r touch -h -d "@${LAYER_EPOCH}"
# Like pip, skip files that do not compile.
changed | { grep -z '\.py$' || true; } | tr '\0' '\n' \
  | { python -m compileall -q -j 0 --invalidation-mode timestamp -i - >/dev/null || true; }
changed | xargs -0r touch -h -d "@${LAYER_EPOCH}"
