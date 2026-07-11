# `lint-vulture` — find dead Python code. Guarded via maybe-tool.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-vulture";
  tool = pkgs.vulture or pkgs.python3Packages.vulture or null;
  description = "Run vulture (dead-code finder) against tracked .py files.";
  build =
    vulture:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-vulture";
      description = "Run vulture (dead-code finder) against tracked .py files.";
      runtimeInputs = [
        vulture
        pkgs.git
      ];
      header = "vulture";
      globs = [ "*.py" ];
      emptyMessage = "(no .py files tracked)";
      command = ''vulture "''${files[@]}"'';
    };
}
