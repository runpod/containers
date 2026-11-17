# `lint-editorconfig` — whitespace / EOL / charset hygiene, as set by a
# `.editorconfig`. The repo has none yet, so this checks nothing until one is
# added (a minimal one flags 65 existing files).

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
