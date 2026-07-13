# Native-parity userland for the prod Nix images. Everything the base image
# pip/apt-installs, expressed as Nix packages (source-built by nixpkgs, hash-
# pinned). Python 3.14 — the latest in nixpkgs.
#
# `mkContents { extraPyPackages, extraTools }` lets pytorch (and future images)
# extend the exact same shared base, so those store paths dedupe across images.

{ pkgs }:

let
  python = pkgs.python314;

  jupyter-archive = import ./pkgs/jupyter-archive.nix {
    inherit python;
    inherit (pkgs) fetchurl;
  };

  # The base image's pip set: jupyterlab, notebook, ipywidgets, hf_transfer,
  # jupyter-archive.
  basePyPackages =
    ps: with ps; [
      jupyterlab
      notebook
      ipywidgets
      hf-transfer
      jupyter-archive
    ];

  # Runtime userland: shell + services + everyday CLI tools. What a *running*
  # pod needs — no compilers. Runtime .so deps of Python packages come in via
  # their own closures.
  coreTools = with pkgs; [
    uv
    filebrowser
    nginx
    openssh

    bashInteractive
    coreutils
    gnugrep
    gnused
    gawk
    findutils
    gnutar
    gzip
    zstd
    curl
    wget
    git
    cacert
    jq
    which
    openssl
    tmux
    vim
    nano
    rsync
    unzip
    zip
    sudo
  ];

  # The apt base's dev/build toolchain (build-essential, cmake, gfortran,
  # pkg-config, ffmpeg). Build-time tooling — heavy, and omitted by the `lean`
  # variant.
  devTools = with pkgs; [
    gcc
    gnumake
    cmake
    gfortran
    pkg-config
    ffmpeg
  ];

  # Full apt-parity userland (core + dev toolchain).
  toolContents = coreTools ++ devTools;

  runpodFiles = pkgs.runCommand "runpod-prod-files" { } ''
    mkdir -p "$out/etc"
    cp ${../../container-template/runpod.txt} "$out/etc/runpod.txt"
  '';

  # `lean` drops the dev/build toolchain — a runtime-only base.
  mkContents =
    {
      extraPyPackages ? (_: [ ]),
      extraTools ? [ ],
      lean ? false,
    }:
    (if lean then coreTools else toolContents)
    ++ extraTools
    ++ [
      (python.withPackages (ps: basePyPackages ps ++ extraPyPackages ps))
      runpodFiles
    ];
in
{
  inherit
    python
    basePyPackages
    coreTools
    devTools
    toolContents
    runpodFiles
    mkContents
    jupyter-archive
    ;

  contents = mkContents { };

  baseEnv = [
    "SHELL=/bin/bash"
    "PYTHONUNBUFFERED=True"
    "LANG=C.UTF-8"
    "LC_ALL=C.UTF-8"
    "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    "TZ=Etc/UTC"
    "RP_WORKSPACE=/workspace"
    "HF_HOME=/workspace/.cache/huggingface/"
    "PIP_CACHE_DIR=/workspace/.cache/pip/"
    "UV_CACHE_DIR=/workspace/.cache/uv/"
    "VIRTUALENV_OVERRIDE_APP_DATA=/workspace/.cache/virtualenv/"
    "HF_HUB_ENABLE_HF_TRANSFER=1"
    "HF_XET_HIGH_PERFORMANCE=1"
    "PIP_BREAK_SYSTEM_PACKAGES=1"
    "PIP_ROOT_USER_ACTION=ignore"
  ];
}
