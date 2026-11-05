# `lint-mypy` — Python type checker (non-strict, ignore-missing-imports
# so third-party deps that aren't installed don't drown the signal).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-mypy";
  description = "Run mypy against tracked .py files.";
  runtimeInputs = [
    pkgs.mypy
    pkgs.git
  ];
  header = "mypy --ignore-missing-imports";
  globs = [ "*.py" ];
  emptyMessage = "(no .py files tracked)";
  command = ''mypy --ignore-missing-imports "''${files[@]}"'';
}
