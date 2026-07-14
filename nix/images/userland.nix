# Shared userland for the PoC images: a faithful subset of what
# official-templates/base installs, expressed as Nix store paths. Consumed by
# base-cpu.nix, base-cuda.nix (hybrid), and family.nix (shared-base family).
#
# `mkContents` lets a family member extend the common userland with extra
# Python packages / tools while reusing the exact same shared store paths — so
# those layers dedupe across every image (see ./footprint.sh, ./README.md).

{ pkgs }:

let
  python = pkgs.python314;

  # Python packages every image gets.
  basePyPackages =
    ps: with ps; [
      jupyterlab
      notebook
      ipywidgets
      hf-transfer
    ];

  # Non-Python userland, shared verbatim by every image (parity with the apt
  # layer's common tools).
  toolContents = [
    pkgs.uv
    pkgs.filebrowser
    pkgs.nginx
    pkgs.openssh
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
  ];

  # Stage the repo's runtime files (entrypoint + banner) into the image root.
  runpodFiles = pkgs.runCommand "runpod-base-files" { } ''
    mkdir -p "$out/etc"
    cp ${../../container-template/start.sh} "$out/start.sh"
    chmod +x "$out/start.sh"
    cp ${../../container-template/runpod.txt} "$out/etc/runpod.txt"
  '';

  # Build a contents list = shared tools + (base + extra) Python env + extra
  # tools. The shared pieces keep identical store paths across all callers.
  mkContents =
    {
      extraPyPackages ? (_: [ ]),
      extraTools ? [ ],
    }:
    toolContents
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
    toolContents
    runpodFiles
    mkContents
    ;

  # Convenience: the plain base userland (no extras).
  contents = mkContents { };

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
