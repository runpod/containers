# `lint-lychee` — link checker for Markdown. Manual/network app: reaches
# out to external URLs, so it is NOT part of `nix flake check`.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-lychee";
  description = "Run lychee link checker against tracked .md files.";
  runtimeInputs = [
    pkgs.lychee
    pkgs.git
  ];
  header = "lychee (network)";
  globs = [ "*.md" ];
  emptyMessage = "(no .md files tracked)";
  command = ''lychee --no-progress "''${files[@]}"'';
}
