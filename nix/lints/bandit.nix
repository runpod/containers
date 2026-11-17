# `lint-bandit` — Python security linter (SAST).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-bandit";
  description = "Run bandit security checks against tracked .py files.";
  runtimeInputs = [
    pkgs.bandit
    pkgs.git
  ];
  header = "bandit";
  globs = [ "*.py" ];
  emptyMessage = "(no .py files tracked)";
  command = ''bandit "''${files[@]}"'';
}
