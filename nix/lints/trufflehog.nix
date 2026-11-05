# `lint-trufflehog` — verified-secret scanner. Manual app: it may reach
# out to validate candidate credentials, so keep it out of the sandbox.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-trufflehog";
  description = "Run trufflehog filesystem scan for secrets.";
  runtimeInputs = [
    pkgs.trufflehog
    pkgs.git
  ];
  header = "trufflehog filesystem";
  command = "trufflehog filesystem . --no-update --fail";
}
