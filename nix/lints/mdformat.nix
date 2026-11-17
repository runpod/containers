# `lint-mdformat` — check Markdown formatting. Guarded via maybe-tool.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-mdformat";
  tool = pkgs.python3Packages.mdformat or null;
  description = "Run mdformat --check against tracked .md files.";
  build =
    mdformat:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-mdformat";
      description = "Run mdformat --check against tracked .md files.";
      runtimeInputs = [
        mdformat
        pkgs.git
      ];
      header = "mdformat --check";
      globs = [ "*.md" ];
      emptyMessage = "(no .md files tracked)";
      command = ''mdformat --check "''${files[@]}"'';
    };
}
