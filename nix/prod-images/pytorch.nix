# Native-parity pytorch images. torch/torchvision/torchaudio come from nixpkgs
# (source-built), extending the same base userland.
#   prod-pytorch-cpu — torch 2.12.0 CPU (cache-friendly; validates the pipeline).
#   prod-pytorch     — torch with cudaSupport=true via a cudaSupport pkgs set;
#                      a heavy from-source CUDA compile (unfree ⇒ not cached).
#
# Single nixpkgs version (2.12.0 / CUDA 12.9), not the repo's wheel matrix —
# see README.

{ pkgs }:

let
  inherit (pkgs) lib;
  runtime = import ./runtime.nix { inherit pkgs; };

  # A cudaSupport nixpkgs so torch + torchvision + torchaudio build against CUDA.
  pkgsCuda = import pkgs.path {
    inherit (pkgs.stdenv.hostPlatform) system;
    config = {
      allowUnfree = true;
      cudaSupport = true;
    };
  };

  torchPkgs =
    ps: with ps; [
      torch
      torchvision
      torchaudio
    ];

  mkPytorch =
    {
      name,
      pkgs',
      pathDirs ? [ ],
      env ? [ ],
    }:
    let
      userland = import ./userland.nix { pkgs = pkgs'; };
    in
    pkgs.dockerTools.streamLayeredImage {
      inherit name;
      tag = "poc";
      contents = (userland.mkContents { extraPyPackages = torchPkgs; }) ++ [ runtime ];
      maxLayers = 100;
      config = {
        Cmd = [ "/start.sh" ];
        WorkingDir = "/";
        Env =
          userland.baseEnv
          ++ [
            "PATH=${
              lib.concatStringsSep ":" (
                [
                  "/bin"
                  "/usr/bin"
                ]
                ++ pathDirs
              )
            }"
          ]
          ++ env;
      };
    };
in
{
  prod-pytorch-cpu = mkPytorch {
    name = "runpod-prod-pytorch-cpu";
    pkgs' = pkgs;
  };

  prod-pytorch = mkPytorch {
    name = "runpod-prod-pytorch-cuda";
    pkgs' = pkgsCuda;
    pathDirs = [ "${pkgsCuda.cudaPackages.cudatoolkit}/bin" ];
    env = [
      "CUDA_HOME=${pkgsCuda.cudaPackages.cudatoolkit}"
      "NVIDIA_VISIBLE_DEVICES=all"
      "NVIDIA_DRIVER_CAPABILITIES=compute,utility"
    ];
  };
}
