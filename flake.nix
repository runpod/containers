{
  description = "runpod/containers — static-analysis surface (Python, shell, Dockerfiles, YAML/GitHub Actions, JSON/TOML, Markdown, Nix, secrets, SAST, supply chain).";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
        # x86_64-darwin dropped: nixpkgs 26.11+ (nixos-unstable) no longer supports it.
        "aarch64-darwin"
      ]
      (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          inherit (pkgs) lib;

          src = lib.cleanSourceWith {
            src = ./.;
            filter =
              path: _type:
              let
                baseName = baseNameOf (toString path);
              in
              baseName != "result"
              && baseName != ".direnv"
              && baseName != ".git"
              && baseName != "node_modules"
              && baseName != "dist"
              && baseName != "build";
          };

          repoLib = import ./nix/lib.nix { inherit pkgs lib; };

          checks = import ./nix/checks.nix { inherit pkgs src; };

          lints = import ./nix/lints { inherit pkgs lib; };

          devShell = import ./nix/devshell { inherit pkgs repoLib; };

          formatter = pkgs.nixfmt-rfc-style;
        in
        {
          inherit checks;

          devShells.default = devShell;

          apps = {
            default =
              lints.apps.lint-extreme or {
                type = "app";
                program = "${pkgs.writeShellScript "default" "echo 'See nix flake show for the static-analysis surface.'"}";
                meta.description = "Default app — points at lint-extreme.";
              };
          }
          // lints.apps;

          inherit formatter;
        }
      );
}
