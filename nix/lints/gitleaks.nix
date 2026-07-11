# `lint-gitleaks` — scan git history + working tree for committed
# secrets. Reads `.gitleaks.toml` at the repo root for allowlists.

{ pkgs, lib }:

import ../lib/mk-lint.nix { inherit pkgs lib; } {
  name = "lint-gitleaks";
  description = "Run gitleaks against the repo for committed secrets.";
  runtimeInputs = [
    pkgs.gitleaks
    pkgs.git
  ];
  header = "gitleaks detect";
  command = "gitleaks detect --source=. --no-banner --redact --verbose";
}
