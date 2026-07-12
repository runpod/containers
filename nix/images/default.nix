# OCI images built with Nix (build-only, experimental — not published).
# Exposed as flake `packages` on Linux systems.
#
# `n2c` (the nix2container builder) is optional; when provided, the *-n2c
# variants are added alongside the dockerTools ones for comparison.

{
  pkgs,
  n2c ? null,
}:

{
  base-cpu = import ./base-cpu.nix { inherit pkgs; };
  base-cuda = import ./base-cuda.nix { inherit pkgs; };
}
// import ./family.nix { inherit pkgs; }
// (
  if n2c != null then
    import ./family-n2c.nix { inherit pkgs n2c; } // import ./family-tiered.nix { inherit pkgs n2c; }
  else
    { }
)
