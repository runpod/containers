# `lint-hadolint` — Dockerfile linter (default failure threshold).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-hadolint";
  description = "Run hadolint against tracked Dockerfiles.";
  runtimeInputs = [
    pkgs.hadolint
    pkgs.git
  ];
  header = "hadolint";
  globs = [
    "Dockerfile"
    "Dockerfile.*"
    "*.Dockerfile"
    "**/Dockerfile"
    "**/Dockerfile.*"
  ];
  emptyMessage = "(no Dockerfile tracked)";
  command = ''hadolint "''${files[@]}"'';
}
