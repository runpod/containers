# Builder for "fan-out" composite apps that run a list of sub-apps
# sequentially, accumulate pass/fail, and exit non-zero if any failed.
# Continues past failures so users get a full report instead of
# stopping at the first broken sub-app.

{ pkgs, lib }:

{
  name,
  subs,
  description,
}:

let
  runEach = lib.concatMapStringsSep "\n" (
    { binName, drv, ... }:
    ''
      echo
      echo "============================================================"
      echo "==> ${binName}"
      echo "============================================================"
      if ${drv}/bin/${binName}; then
        passes=$((passes + 1))
      else
        fails=$((fails + 1))
        failed_names="$failed_names ${binName}"
      fi
    ''
  ) subs;
in
pkgs.writeShellApplication {
  inherit name;
  text = ''
    set -uo pipefail
    passes=0
    fails=0
    failed_names=""
    ${runEach}
    echo
    echo "============================================================"
    echo "Summary: $passes passed, $fails failed"
    if [ "$fails" -gt 0 ]; then
      echo "Failed:$failed_names"
    fi
    echo "============================================================"
    [ "$fails" -eq 0 ] || exit 1
  '';
  meta.description = description;
}
