# `lint-osv` — scan dependency manifests against the OSV database.
# Manual/network app.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-osv";
  description = "Run osv-scanner against dependency manifests.";
  runtimeInputs = [
    pkgs.osv-scanner
    pkgs.git
  ];
  header = "osv-scanner (network)";
  command = "osv-scanner scan --recursive .";
}
