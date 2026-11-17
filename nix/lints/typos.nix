# `lint-typos` — source-code spell checker (low false-positive). Reads
# `_typos.toml` / `typos.toml` if present.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-typos";
  description = "Run typos spell checker against the tree.";
  runtimeInputs = [
    pkgs.typos
    pkgs.git
  ];
  header = "typos";
  command = "typos";
}
