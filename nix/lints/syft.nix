# `lint-syft` — generate an SBOM of the tree. Informational; always
# exits 0 unless syft itself errors.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-syft";
  description = "Generate an SBOM of the tree with syft.";
  runtimeInputs = [
    pkgs.syft
    pkgs.git
  ];
  header = "syft (SBOM)";
  command = "syft dir:. --output table";
}
