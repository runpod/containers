# `lint-hadolint` — Dockerfile linter (default failure threshold), with the
# ignores in ../hadolint.yaml.

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
  command = ''hadolint -c nix/hadolint.yaml "''${files[@]}"'';
}
