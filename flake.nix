# runpod/containers: pinned static analysis and Nix-built images.
#
# Quick start (see nix/README.md):
#   nix develop                   # shell with every tool on PATH
#   nix flake check               # the gated checks CI runs
#   nix run .#lint-py             # one domain: lint-shell, lint-docker, lint-yaml, ...
#   nix run .#lint-trivy          # one tool (nix flake show lists them all)
#   nix run .#everything          # every tool
#   nix fmt                       # format the Nix files
#
# Images (x86_64-linux; see nix/images/README.md):
#   nix build .#nix-pytorch-cuda && ./result | docker load
#   nix run .#image-size          # build them all, compare with Docker Hub
#   nix run .#image-smoke -- nix-base-cpu   # SSH, Jupyter, nginx checks in Docker
#
# Every tool is pinned by flake.lock; nothing is installed globally.

{
  description = "runpod/containers static analysis (Python, shell, Dockerfiles, YAML/GitHub Actions, JSON/TOML, Markdown, Nix, secrets, supply chain) and Nix-built images";

  inputs = {
    # Channel tarball, as `nix flake init` now emits: no GitHub API calls, and
    # the channel only advances once Hydra has built (and cached) it.
    nixpkgs.url = "https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.zst";
  };

  outputs =
    { nixpkgs, ... }:
    let
      inherit (nixpkgs) lib;

      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});

      src = lib.cleanSourceWith {
        src = ./.;
        filter =
          path: _type:
          !builtins.elem (baseNameOf (toString path)) [
            "result"
            ".direnv"
            ".git"
            "node_modules"
            "dist"
            "build"
          ];
      };

      repoLib = import ./nix/lib.nix { };
    in
    {
      formatter = forAllSystems (pkgs: pkgs.nixfmt);

      checks = forAllSystems (pkgs: import ./nix/checks.nix { inherit pkgs src; });

      devShells = forAllSystems (pkgs: {
        default = import ./nix/devshell { inherit pkgs repoLib; };
      });

      apps = forAllSystems (
        pkgs:
        (import ./nix/lints { inherit pkgs lib; }).apps
        // {
          image-size = {
            type = "app";
            program = lib.getExe (import ./nix/images/size.nix { inherit pkgs; });
            meta.description = "Build the Nix images and compare their size with the published ones.";
          };
          image-smoke = {
            type = "app";
            program = lib.getExe (import ./nix/images/smoke.nix { inherit pkgs; });
            meta.description = "Run a Nix image in Docker and check SSH, Jupyter, nginx, pip and nix-ld.";
          };
        }
      );

      # Nix-built container images (build-only). x86_64-linux only.
      packages = lib.genAttrs systems (system: import ./nix/images { inherit nixpkgs system; });
    };
}
