# `lint-vale` — prose linter. Guarded via maybe-tool; only meaningful
# with a `.vale.ini` in the repo, otherwise it no-ops cleanly.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-vale";
  tool = pkgs.vale or null;
  description = "Run vale prose linter against tracked .md files.";
  build =
    vale:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-vale";
      description = "Run vale prose linter against tracked .md files.";
      runtimeInputs = [
        vale
        pkgs.git
      ];
      header = "vale";
      command = ''
        if [ ! -f .vale.ini ]; then
          echo "    (no .vale.ini config — skipping)"
          exit 0
        fi
        mapfile -t files < <(git ls-files '*.md')
        if [ "''${#files[@]}" -eq 0 ]; then
          echo "    (no .md files tracked)"
          exit 0
        fi
        vale "''${files[@]}"
      '';
    };
}
