# `lint-actionlint` — validate GitHub Actions workflow files.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-actionlint";
  description = "Run actionlint against .github/workflows.";
  runtimeInputs = [
    pkgs.actionlint
    pkgs.git
  ];
  header = "actionlint";
  command = ''
    if [ -d .github/workflows ]; then
      actionlint
    else
      echo "    (no .github/workflows directory)"
    fi
  '';
}
