# `lint-shfmt` — report shell-formatting diffs (does not rewrite files).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-shfmt";
  description = "Run shfmt --diff against tracked shell files.";
  runtimeInputs = [
    pkgs.shfmt
    pkgs.git
  ];
  header = "shfmt --diff";
  globs = [
    "*.sh"
    "*.bash"
  ];
  emptyMessage = "(no shell files tracked)";
  command = ''shfmt --diff "''${files[@]}"'';
}
