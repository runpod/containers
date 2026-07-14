# `lint-cspell` — spell checker. Guarded via maybe-tool; reads
# `cspell.json` if present.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-cspell";
  tool = pkgs.cspell or null;
  description = "Run cspell against the tree.";
  build =
    cspell:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-cspell";
      description = "Run cspell against the tree.";
      runtimeInputs = [
        cspell
        pkgs.git
      ];
      header = "cspell";
      command = ''cspell --no-progress --no-must-find-files "**/*.{md,py,sh,yml,yaml,json}"'';
    };
}
