# `lint-markdown` — markdownlint over tracked Markdown. Reads
# `.markdownlint.yaml` at the repo root.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-markdown";
  description = "Run markdownlint-cli2 against tracked .md files.";
  runtimeInputs = [
    pkgs.markdownlint-cli2
    pkgs.git
  ];
  header = "markdownlint-cli2";
  command = ''
    markdownlint-cli2 \
      '**/*.md' \
      '!node_modules/**' \
      '!dist/**' \
      '!build/**'
  '';
}
