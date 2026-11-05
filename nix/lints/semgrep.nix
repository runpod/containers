# `lint-semgrep` — multi-language SAST. Manual app: the default rule
# registry (`--config auto`) fetches rules over the network. Uses the
# offline `p/default` ruleset bundled with the package here.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-semgrep";
  description = "Run semgrep SAST against the tree.";
  runtimeInputs = [
    pkgs.semgrep
    pkgs.git
  ];
  header = "semgrep --config p/default";
  command = "semgrep --error --config p/default --quiet .";
}
