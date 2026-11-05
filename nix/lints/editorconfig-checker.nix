# `lint-editorconfig` — whitespace / EOL / charset hygiene. Honors a
# `.editorconfig` if present; otherwise applies its built-in defaults.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-editorconfig";
  description = "Run editorconfig-checker against the tree.";
  runtimeInputs = [
    pkgs.editorconfig-checker
    pkgs.git
  ];
  header = "editorconfig-checker";
  command = "editorconfig-checker";
}
