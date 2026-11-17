# `lint-bashate` — style checks for bash (indentation, quoting, ...).
# Guarded via maybe-tool: not packaged in every nixpkgs pin.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-bashate";
  tool = pkgs.bashate or null;
  description = "Run bashate against tracked shell files.";
  build =
    bashate:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-bashate";
      description = "Run bashate against tracked shell files.";
      runtimeInputs = [
        bashate
        pkgs.git
      ];
      header = "bashate";
      globs = [
        "*.sh"
        "*.bash"
      ];
      emptyMessage = "(no shell files tracked)";
      command = ''bashate "''${files[@]}"'';
    };
}
