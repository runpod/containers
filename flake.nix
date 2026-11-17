# runpod/containers: pinned static analysis, built with Nix.
#
# Quick start (see nix/README.md):
#   nix develop                   # shell with every tool on PATH
#   nix flake check               # the gated checks CI runs
#   nix run .#lint-py             # one domain: lint-shell, lint-docker, lint-yaml, ...
#   nix run .#lint-trivy          # one tool (nix flake show lists them all)
#   nix run .#everything          # every tool
#   nix fmt                       # format the Nix files
#
# Every tool is pinned by flake.lock; nothing is installed globally.

{
  description = "runpod/containers static analysis (Python, shell, Dockerfiles, YAML/GitHub Actions, JSON/TOML, Markdown, Nix, secrets, supply chain)";

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

      apps = forAllSystems (pkgs: (import ./nix/lints { inherit pkgs lib; }).apps);
    };
}
