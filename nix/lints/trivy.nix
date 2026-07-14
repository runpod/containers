# `lint-trivy` — filesystem vulnerability + misconfiguration scan.
# Manual/network app: pulls its vulnerability DB.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-trivy";
  description = "Run trivy filesystem scan (vuln + misconfig).";
  runtimeInputs = [
    pkgs.trivy
    pkgs.git
  ];
  header = "trivy fs (network)";
  command = "trivy fs --scanners vuln,misconfig,secret --exit-code 1 .";
}
