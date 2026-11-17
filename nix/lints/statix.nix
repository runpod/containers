# `lint-statix` — flag Nix antipatterns.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-statix";
  description = "Run statix antipattern check against the tree.";
  runtimeInputs = [
    pkgs.statix
    pkgs.git
  ];
  header = "statix check .";
  command = "statix check .";
}
