# Nix-built counterparts of runpod/base and runpod/pytorch, from nixpkgs alone:
# no Ubuntu base, no apt, no pip. Build-only; nothing is published.
# See ./README.md for the comparison against the published images.

{ nixpkgs, system }:

let
  pkgs = nixpkgs.legacyPackages.${system};
  inherit (pkgs) lib;

  # CUDA is unfree; allow it only in the package set that needs it.
  pkgsCuda = import nixpkgs {
    inherit system;
    config = {
      allowUnfree = true;
      cudaSupport = true;
    };
  };
  pkgsRocm = import nixpkgs {
    inherit system;
    config.rocmSupport = true;
  };

  mkImage =
    {
      name,
      pkgs',
      dev ? true,
      extraPyPackages ? (_: [ ]),
      extraContents ? [ ],
      env ? [ ],
      extraRootCommands ? "",
    }:
    let
      userland = import ./userland.nix { pkgs = pkgs'; };
      runtime = import ./runtime.nix {
        pkgs = pkgs';
        inherit (userland) loaderEnv;
      };
    in
    pkgs'.dockerTools.streamLayeredImage {
      inherit name;
      tag = "nix";
      contents =
        userland.mkContents { inherit dev extraPyPackages; } ++ runtime.contents ++ extraContents;
      fakeRootCommands = runtime.rootCommands + extraRootCommands;
      config = {
        Cmd = [ "/start.sh" ];
        WorkingDir = "/";
        Env = userland.env ++ [ "PATH=/bin:/usr/bin" ] ++ env;
      };
    };

  # nvidia-container-toolkit mounts the driver libraries into
  # /usr/lib/x86_64-linux-gnu when that directory exists. nixpkgs' CUDA
  # packages look for them in /run/opengl-driver/lib, so point one at the
  # other.
  nvidiaDriverLink = ''
    mkdir -p usr/lib/x86_64-linux-gnu run/opengl-driver
    ln -s /usr/lib/x86_64-linux-gnu run/opengl-driver/lib
  '';
  nvidiaEnv = [
    "NVIDIA_VISIBLE_DEVICES=all"
    "NVIDIA_DRIVER_CAPABILITIES=all"
  ];

  # The -devel CUDA images' toolkit: nvcc, headers, libraries and cuDNN.
  cuda = pkgsCuda.cudaPackages;
  cudaToolkit = pkgsCuda.symlinkJoin {
    name = "cuda-toolkit-${cuda.cudaMajorMinorVersion}";
    paths = [
      cuda.cudatoolkit
      cuda.cudnn
    ];
  };

  torch =
    ps: with ps; [
      torch
      torchaudio
      torchvision
    ];
in
lib.optionalAttrs (system == "x86_64-linux") {
  nix-base-cpu = mkImage {
    name = "runpod-nix-base-cpu";
    pkgs' = pkgs;
  };

  # The floor: drops the build toolchain, which a running pod rarely needs.
  nix-base-cpu-runtime = mkImage {
    name = "runpod-nix-base-cpu-runtime";
    pkgs' = pkgs;
    dev = false;
  };

  nix-base-cuda = mkImage {
    name = "runpod-nix-base-cuda";
    pkgs' = pkgsCuda;
    extraContents = [ cudaToolkit ];
    extraRootCommands = nvidiaDriverLink;
    env = nvidiaEnv ++ [ "CUDA_HOME=${cudaToolkit}" ];
  };

  nix-pytorch-cuda = mkImage {
    name = "runpod-nix-pytorch-cuda";
    pkgs' = pkgsCuda;
    extraPyPackages = torch;
    extraRootCommands = nvidiaDriverLink;
    env = nvidiaEnv;
  };

  nix-pytorch-rocm = mkImage {
    name = "runpod-nix-pytorch-rocm";
    pkgs' = pkgsRocm;
    extraPyPackages = torch;
  };
}
