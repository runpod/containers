# `lint-taplo` — validate TOML files.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-taplo";
  description = "Run taplo check against tracked .toml files.";
  runtimeInputs = [
    pkgs.taplo
    pkgs.git
  ];
  header = "taplo check";
  globs = [ "*.toml" ];
  emptyMessage = "(no .toml files tracked)";
  command = ''taplo check "''${files[@]}"'';
}
