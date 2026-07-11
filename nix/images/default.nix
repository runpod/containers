# OCI images built with Nix (build-only, experimental — not published).
# Exposed as flake `packages` on Linux systems.

{ pkgs }:

{
  base-cpu = import ./base-cpu.nix { inherit pkgs; };
}
