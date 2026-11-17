# `lint-nil` — nil language-server diagnostics over tracked Nix files.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-nil";
  description = "Run nil diagnostics against tracked .nix files.";
  runtimeInputs = [
    pkgs.nil
    pkgs.git
  ];
  header = "nil diagnostics";
  globs = [ "*.nix" ];
  emptyMessage = "(no .nix files tracked)";
  command = ''
    failed=0
    for f in "''${files[@]}"; do
      diag=$(nil diagnostics "$f" 2>&1) || failed=1
      if [ -n "$diag" ]; then
        printf '=== %s ===\n%s\n' "$f" "$diag"
        failed=1
      fi
    done
    exit "$failed"
  '';
}
