# `lint-deadnix` — find unused Nix bindings.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-deadnix";
  description = "Run deadnix --fail against tracked .nix files.";
  runtimeInputs = [
    pkgs.deadnix
    pkgs.git
  ];
  header = "deadnix --fail";
  globs = [ "*.nix" ];
  emptyMessage = "(no .nix files tracked)";
  command = ''deadnix --fail "''${files[@]}"'';
}
