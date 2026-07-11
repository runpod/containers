# Proof-of-concept: build the runpod/base CPU image with Nix instead of a
# Dockerfile, for a build-only size/determinism comparison. NOT published.
#
# Faithful subset of official-templates/base (CPU variant): a Python 3.12
# environment with JupyterLab + notebook + ipywidgets + hf_transfer, plus uv,
# filebrowser, nginx, openssh and the common CLI tooling, launched via the
# repo's start.sh. GPU/CUDA parity and multi-Python are out of scope here (see
# ./README.md).
#
# Built with dockerTools.streamLayeredImage: deterministic (no timestamps /
# build-host entropy), daemon-less, and automatically split into content-
# addressed layers so shared store paths dedupe across images.

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
pkgs.dockerTools.streamLayeredImage {
  name = "runpod-base-cpu-nix";
  tag = "poc";

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

  config = {
    Cmd = [ "/start.sh" ];
    WorkingDir = "/";
    Env = [
      "PATH=/bin:/usr/bin"
      "SHELL=/bin/bash"
      "PYTHONUNBUFFERED=True"
      "LANG=C.UTF-8"
      "LC_ALL=C.UTF-8"
      "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      "TZ=Etc/UTC"
      "RP_WORKSPACE=/workspace"
      "HF_HUB_ENABLE_HF_TRANSFER=1"
    ];
  };
}
