# `lint-jsonlint` — validate JSON well-formedness. Uses the Python
# stdlib json parser (always available) so it needs no extra package;
# useful for the large generated Grafana dashboard JSON in this repo.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-jsonlint";
  description = "Validate tracked .json files parse cleanly.";
  runtimeInputs = [
    pkgs.python3
    pkgs.git
  ];
  header = "python -m json.tool (validate)";
  globs = [ "*.json" ];
  emptyMessage = "(no .json files tracked)";
  command = ''
    failed=0
    for f in "''${files[@]}"; do
      if ! python3 -m json.tool "$f" >/dev/null 2>err.txt; then
        echo "=== $f ==="
        cat err.txt
        failed=1
      fi
    done
    rm -f err.txt
    exit "$failed"
  '';
}
