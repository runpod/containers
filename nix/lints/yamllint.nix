# `lint-yamllint` — yamllint over tracked YAML. Reads `.yamllint.yaml`
# at the repo root for the project's relaxed rule set.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-yamllint";
  description = "Run yamllint against tracked .yml / .yaml files.";
  runtimeInputs = [
    pkgs.yamllint
    pkgs.git
  ];
  header = "yamllint";
  globs = [
    "*.yml"
    "*.yaml"
  ];
  emptyMessage = "(no .yml / .yaml files tracked)";
  command = ''yamllint "''${files[@]}"'';
}
