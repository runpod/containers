# `lint-nixfmt` — check Nix formatting (RFC style).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-nixfmt";
  description = "Run nixfmt --check against tracked .nix files.";
  runtimeInputs = [
    pkgs.nixfmt-rfc-style
    pkgs.git
  ];
  header = "nixfmt --check";
  globs = [ "*.nix" ];
  emptyMessage = "(no .nix files tracked)";
  command = ''nixfmt --check "''${files[@]}"'';
}
