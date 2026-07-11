# Proof-of-concept: HYBRID CUDA image — pin NVIDIA's tested CUDA base as
# `fromImage` and layer the deterministic Nix userland on top. Build-only,
# NOT published.
#
# Directly comparable to runpod/base:<ver>-cuda1281-ubuntu2404, which is the
# same nvidia/cuda devel base + an apt/5-python/jupyter userland layer. Torch
# is pip-installed on top of BOTH identically (see the pytorch template), so
# excluding it here keeps the comparison of the *userland layer* fair.
#
# The base is pinned by digest + Nix hash (from `nix-prefetch-docker`); bump
# both together when the CUDA version in shared/versions.hcl changes:
#   nix run nixpkgs#nix-prefetch-docker -- \
#     --image-name nvidia/cuda --image-tag <tag> --arch amd64 --os linux

{ pkgs }:

let
  userland = import ./userland.nix { inherit pkgs; };

  cudaBase = pkgs.dockerTools.pullImage {
    imageName = "nvidia/cuda";
    imageDigest = "sha256:24c8e3581ea6330038b0d374920721983312627f8adbfcf390bdb4b399d280ed";
    hash = "sha256-SY6Xgmrn9K2Owl0Hel7uM+6KO12Uua5hKqVCLt9gjKw=";
    finalImageName = "nvidia/cuda";
    finalImageTag = "12.8.1-cudnn-devel-ubuntu24.04";
  };
in
pkgs.dockerTools.streamLayeredImage {
  name = "runpod-base-cuda-nix";
  tag = "poc";

  fromImage = cudaBase;
  inherit (userland) contents;

  config = {
    Cmd = [ "/start.sh" ];
    WorkingDir = "/";
    # NOTE: streamLayeredImage does not inherit the base image's env, so we
    # re-declare the CUDA paths a runnable image needs. Env does not affect the
    # size measurement; a production hybrid would merge the base's full env.
    Env = userland.baseEnv ++ [
      "PATH=/bin:/usr/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin"
      "LD_LIBRARY_PATH=/usr/local/nvidia/lib:/usr/local/nvidia/lib64"
      "NVIDIA_VISIBLE_DEVICES=all"
      "NVIDIA_DRIVER_CAPABILITIES=compute,utility"
    ];
  };
}
