# `lint-pylint` — thorough Python linter. Manual app: some checks want
# imports resolvable. `--exit-zero` is NOT used; treats findings as fail.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-pylint";
  description = "Run pylint against tracked .py files.";
  runtimeInputs = [
    pkgs.pylint
    pkgs.git
  ];
  header = "pylint";
  globs = [ "*.py" ];
  emptyMessage = "(no .py files tracked)";
  command = ''pylint "''${files[@]}"'';
}
