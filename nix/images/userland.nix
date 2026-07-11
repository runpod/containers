# Shared userland for the PoC images: a faithful subset of what
# official-templates/base installs, expressed as Nix store paths. Consumed by
# both base-cpu.nix (no base image) and base-cuda.nix (layered on nvidia/cuda).

{ pkgs }:

let
  python = pkgs.python314;

  pyEnv = python.withPackages (
    ps: with ps; [
      jupyterlab
      notebook
      ipywidgets
      hf-transfer
    ]
  );

  # Stage the repo's runtime files (entrypoint + banner) into the image root.
  runpodFiles = pkgs.runCommand "runpod-base-files" { } ''
    mkdir -p "$out/etc"
    cp ${../../container-template/start.sh} "$out/start.sh"
    chmod +x "$out/start.sh"
    cp ${../../container-template/runpod.txt} "$out/etc/runpod.txt"
  '';
in
{
  inherit pyEnv runpodFiles;

  contents = [
    pyEnv
    pkgs.uv
    pkgs.filebrowser
    pkgs.nginx
    pkgs.openssh

    # Shell + core userland (parity with the apt layer's common tools).
    pkgs.bashInteractive
    pkgs.coreutils
    pkgs.gnused
    pkgs.gnugrep
    pkgs.gawk
    pkgs.findutils
    pkgs.gnutar
    pkgs.gzip
    pkgs.zstd
    pkgs.curl
    pkgs.wget
    pkgs.git
    pkgs.cacert
    pkgs.jq
    pkgs.which
    pkgs.openssl
    pkgs.tmux
    pkgs.vim
    pkgs.nano
    pkgs.rsync
    pkgs.unzip
    pkgs.zip

    runpodFiles
  ];

  # Env shared by both images. base-cuda extends PATH/LD_LIBRARY_PATH with the
  # CUDA directories from the nvidia base.
  baseEnv = [
    "SHELL=/bin/bash"
    "PYTHONUNBUFFERED=True"
    "LANG=C.UTF-8"
    "LC_ALL=C.UTF-8"
    "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    "TZ=Etc/UTC"
    "RP_WORKSPACE=/workspace"
    "HF_HUB_ENABLE_HF_TRANSFER=1"
  ];
}
