# Native-parity base images, built with dockerTools.streamLayeredImage.
#   prod-base-cpu  — userland + runtime, no GPU.
#   prod-base-cuda — + full-Nix cudaPackages (CUDA toolkit + cuDNN from nixpkgs
#                    redistributables, hash-pinned) on PATH/LD_LIBRARY_PATH.
#
# No vendor nvidia/cuda base image — CUDA comes entirely from nixpkgs.

{ pkgs }:

let
  inherit (pkgs) lib;
  userland = import ./userland.nix { inherit pkgs; };
  runtime = import ./runtime.nix { inherit pkgs; };
  cuda = pkgs.cudaPackages;

  mkImage =
    {
      name,
      contents ? userland.contents,
      extraContents ? [ ],
      pathDirs ? [ ],
      env ? [ ],
    }:
    pkgs.dockerTools.streamLayeredImage {
      inherit name;
      tag = "poc";
      contents = contents ++ [ runtime ] ++ extraContents;
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
  prod-base-cpu = mkImage { name = "runpod-prod-base-cpu"; };

  # Runtime-only CPU base: drops the gcc/gfortran/cmake/ffmpeg dev toolchain.
  prod-base-cpu-lean = mkImage {
    name = "runpod-prod-base-cpu-lean";
    contents = userland.mkContents { lean = true; };
  };

  prod-base-cuda = mkImage {
    name = "runpod-prod-base-cuda";
    extraContents = [
      cuda.cudatoolkit
      cuda.cudnn
    ];
    pathDirs = [ "${cuda.cudatoolkit}/bin" ];
    env = [
      "LD_LIBRARY_PATH=${cuda.cudatoolkit}/lib:${cuda.cudnn}/lib"
      "CUDA_HOME=${cuda.cudatoolkit}"
      "NVIDIA_VISIBLE_DEVICES=all"
      "NVIDIA_DRIVER_CAPABILITIES=compute,utility"
    ];
  };
}
