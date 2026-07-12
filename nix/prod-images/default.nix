# Native-parity ("prod") Nix container images — build-only, not published.
# Kept separate from the experimental nix/images/* PoC so both can be compared.

{ pkgs }:

(import ./base.nix { inherit pkgs; }) // (import ./pytorch.nix { inherit pkgs; })
