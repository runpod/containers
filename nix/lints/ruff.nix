# `lint-ruff` — fast Python linter (default rule set; reads
# `pyproject.toml` `[tool.ruff]` if present).

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-ruff";
  description = "Run ruff check against tracked .py files.";
  runtimeInputs = [
    pkgs.ruff
    pkgs.git
  ];
  header = "ruff check";
  globs = [ "*.py" ];
  emptyMessage = "(no .py files tracked)";
  command = ''ruff check "''${files[@]}"'';
}
