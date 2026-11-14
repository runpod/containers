# `lint-shellcheck` — shellcheck over tracked shell scripts (default
# severity; `-x` follows `source` directives).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-shellcheck";
  description = "Run shellcheck against tracked .sh / .bash files.";
  runtimeInputs = [
    pkgs.shellcheck
    pkgs.git
  ];
  header = "shellcheck -x";
  globs = [
    "*.sh"
    "*.bash"
  ];
  emptyMessage = "(no .sh / .bash files tracked)";
  command = ''
    printf '    %s\n' "''${files[@]}"
    shellcheck -x "''${files[@]}"
  '';
}
