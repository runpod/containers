# `lint-biome` — Biome as a fast JSON linter/format-checker (second
# opinion to jsonlint). Reads `biome.json` if present; otherwise runs
# with defaults over the tree.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-biome";
  description = "Run biome check (JSON) against the tree.";
  runtimeInputs = [
    pkgs.biome
    pkgs.git
  ];
  header = "biome check";
  command = "biome check --reporter=summary .";
}
