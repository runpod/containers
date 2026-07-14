# `lint-detect-secrets` — Yelp detect-secrets scan. Guarded via
# maybe-tool.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-detect-secrets";
  tool = pkgs.detect-secrets or pkgs.python3Packages.detect-secrets or null;
  description = "Run detect-secrets scan against the tree.";
  build =
    detect-secrets:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-detect-secrets";
      description = "Run detect-secrets scan against the tree.";
      runtimeInputs = [
        detect-secrets
        pkgs.git
      ];
      header = "detect-secrets scan";
      command = ''
        # Non-zero exit when any secret is detected.
        found=$(detect-secrets scan --all-files | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(len(v) for v in d.get("results",{}).values()))')
        echo "    detected candidate secrets: $found"
        [ "$found" -eq 0 ]
      '';
    };
}
