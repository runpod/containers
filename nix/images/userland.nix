# Shared userland: what official-templates/base installs with apt and pip,
# as nixpkgs packages. Every image builds on this, so its store paths (and
# their layers) are the same across images built from the same pkgs set.

{ pkgs }:

let
  # Overriding anything in this package set (even tornado) rebuilds torch
  # from source, so the images take nixpkgs' versions as they are.
  python = pkgs.python314;
  jupyter-archive = python.pkgs.callPackage ./pkgs/jupyter-archive.nix { };

  # official-templates/base/requirements.txt, plus the pip and virtualenv the
  # Dockerfile installs. requirements.txt pins tornado 6.5.10 to avoid 6.5.9's
  # blank JupyterLab page (#168); nixpkgs' 6.5.8 predates that bug.
  basePyPackages =
    ps: with ps; [
      hf-transfer
      ipywidgets
      jupyter-archive
      jupyterlab
      notebook
      pip
      tornado
      virtualenv
    ];

  # Libraries pip wheels and prebuilt binaries expect from the distro
  # (libstdc++, zlib, and libGL/libSM/libXrender for opencv), found by
  # neither Nix's loader nor, without nix-ld, a foreign binary's.
  manylinuxLibs = pkgs.lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux2014;

  # The apt list's runtime tools.
  runtimeTools = with pkgs; [
    bashInteractive
    bzip2
    cacert
    coreutils
    curl
    dnsutils
    file
    findutils
    gawk
    getent
    git
    gnugrep
    gnupg
    gnused
    gnutar
    gzip
    inotify-tools
    iproute2
    iputils
    jq
    less
    lsof
    mtr
    nano
    nginx
    openssh
    procps
    rsync
    tmux
    traceroute
    unzip
    util-linux
    uv
    vim
    wget
    which
    xz
    zip
    zstd
  ];

  # The apt list's build toolchain (build-essential, cmake, gfortran,
  # pkg-config, ffmpeg). torch.compile needs a C compiler at run time.
  devTools = with pkgs; [
    cmake
    ffmpeg-headless
    gcc
    gfortran
    gnumake
    pkg-config
  ];
in
rec {
  inherit python;

  # `dev` adds the build toolchain; `extraPyPackages` extends the Python env
  # (e.g. torch) so there's still a single interpreter on PATH.
  mkContents =
    {
      dev ? true,
      extraPyPackages ? (_: [ ]),
    }:
    runtimeTools
    ++ pkgs.lib.optionals dev devTools
    ++ [ (python.withPackages (ps: basePyPackages ps ++ extraPyPackages ps)) ];

  # official-templates/base/Dockerfile ENV.
  env = [
    "SHELL=/bin/bash"
    "PYTHONUNBUFFERED=True"
    "TZ=Etc/UTC"
    "LANG=C.UTF-8"
    "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    "RP_WORKSPACE=/workspace"
    "HF_HOME=/workspace/.cache/huggingface/"
    "VIRTUALENV_OVERRIDE_APP_DATA=/workspace/.cache/virtualenv/"
    "PIP_CACHE_DIR=/workspace/.cache/pip/"
    "UV_CACHE_DIR=/workspace/.cache/uv/"
    "HF_HUB_ENABLE_HF_TRANSFER=1"
    "HF_XET_HIGH_PERFORMANCE=1"
    "PIP_BREAK_SYSTEM_PACKAGES=1"
    "PIP_ROOT_USER_ACTION=ignore"
  ]
  ++ loaderEnv;

  # Non-Nix binaries (uv-managed Pythons, VS Code server) start through nix-ld
  # at /lib64/ld-linux-x86-64.so.2 (see runtime.nix). SSH sessions don't
  # inherit the image ENV, so sshd sets these too.
  loaderEnv = [
    "LD_LIBRARY_PATH=${manylinuxLibs}"
    "NIX_LD=${pkgs.stdenv.cc.bintools.dynamicLinker}"
    "NIX_LD_LIBRARY_PATH=${manylinuxLibs}"
  ];
}
