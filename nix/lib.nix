# Shared helpers for this repo's static-analysis flake. A slim "lib
# namespace root": specialized builders (`mk-lint.nix`, `mk-all-app.nix`,
# `mk-check.nix`, `maybe-tool.nix`) live alongside as `nix/lib/<name>.nix`
# and are imported by their consumers.

_:

let
  # Marker used by every lint app's banner.
  repoName = "runpod-containers";
in
{
  inherit repoName;
}
