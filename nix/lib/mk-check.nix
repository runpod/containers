# Shared builder for `nix flake check` gated derivations. Each check
# stages `src` into a writable workdir, runs `script`, and writes
# `$out` on success. Tools that need network access (osv-scanner,
# trivy, lychee, trufflehog) cannot use this helper — expose them as
# `nix run .#lint-*` apps only.

{ pkgs, src }:

{
  name,
  buildInputs ? [ ],
  script,
}:

pkgs.runCommand name { nativeBuildInputs = buildInputs; } ''
  set -euo pipefail
  workdir=$(mktemp -d)
  cd "$workdir"
  cp -r ${src}/. ./
  chmod -R u+w .
  ${script}
  touch $out
''
