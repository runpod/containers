# `lint-codespell` — common-misspelling checker. Skips binary and
# generated paths.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-codespell";
  description = "Run codespell against the tree.";
  runtimeInputs = [
    pkgs.codespell
    pkgs.git
  ];
  header = "codespell";
  command = "codespell --skip='.git,*.svg,*.lock,node_modules,result,result-*' .";
}
