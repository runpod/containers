{
  description = "runpod/containers — static-analysis surface (Python, shell, Dockerfiles, YAML/GitHub Actions, JSON/TOML, Markdown, Nix, secrets, SAST, supply chain).";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # For the experimental nix2container image targets (compared against
    # dockerTools). Follows our nixpkgs so there's only one pin.
    nix2container.url = "github:nlewo/nix2container";
    nix2container.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      nix2container,
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

          # Experimental Nix-built OCI images (build-only, not published).
          # Linux-only — these are Linux container images. Passing the
          # nix2container builder in adds the *-n2c variants for comparison.
          n2c = nix2container.packages.${system};
          images = lib.optionalAttrs pkgs.stdenv.isLinux (
            import ./nix/images {
              inherit pkgs;
              n2c = n2c.nix2container;
            }
          );

          # Native-parity ("prod") images — a separate tree from the PoC above,
          # rebuilding base + pytorch entirely from nixpkgs (source builds,
          # full-Nix CUDA). Build-only, not published.
          prodImages = lib.optionalAttrs pkgs.stdenv.isLinux (import ./nix/prod-images { inherit pkgs; });

          formatter = pkgs.nixfmt-rfc-style;
        in
        {
          inherit checks;

          packages =
            images
            // prodImages
            // lib.optionalAttrs pkgs.stdenv.isLinux {
              # Patched skopeo that understands nix2container's `nix:` transport,
              # used by footprint.sh to inspect the n2c images' real OCI layers.
              skopeo-n2c = n2c.skopeo-nix2container;
            };

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
