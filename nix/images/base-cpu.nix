# Proof-of-concept: build the runpod/base CPU image with Nix instead of a
# Dockerfile, for a build-only size/determinism comparison. NOT published.
#
# Faithful subset of official-templates/base (CPU variant); see ./userland.nix
# for the package set. GPU/CUDA parity lives in ./base-cuda.nix.
#
# Built with dockerTools.streamLayeredImage: deterministic (no timestamps /
# build-host entropy), daemon-less, and automatically split into content-
# addressed layers so shared store paths dedupe across images.

{ pkgs }:

let
  userland = import ./userland.nix { inherit pkgs; };
in
pkgs.dockerTools.streamLayeredImage {
  name = "runpod-base-cpu-nix";
  tag = "poc";

  inherit (userland) contents;

  config = {
    Cmd = [ "/start.sh" ];
    WorkingDir = "/";
    Env = userland.baseEnv ++ [ "PATH=/bin:/usr/bin" ];
  };
}
