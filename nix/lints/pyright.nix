# `lint-pyright` — Python type checker. Manual app: import resolution
# needs the project's dependencies available on the interpreter path.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-pyright";
  description = "Run pyright against tracked .py files.";
  runtimeInputs = [
    pkgs.pyright
    pkgs.git
  ];
  header = "pyright";
  globs = [ "*.py" ];
  emptyMessage = "(no .py files tracked)";
  command = ''pyright "''${files[@]}"'';
}
