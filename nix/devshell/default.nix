# Development shell. Contains every tool the lint apps need so a
# contributor with `nix develop` can run any `nix run .#lint-*`
# without further setup.

{ pkgs, repoLib }:

let
  packages = import ./packages.nix { inherit pkgs; };
in
pkgs.mkShell {
  inherit packages;
  meta.description = "runpod/containers static-analysis toolchain (Python, shell, Docker, YAML/Actions, JSON/TOML, Markdown, Nix, secrets, SAST, supply chain).";

  shellHook = ''
    echo "  ${repoLib.repoName} — static-analysis shell"
    echo
    echo "  Composites:"
    echo "    nix run .#lint-shell       # shellcheck, shfmt, bashate, checkbashisms"
    echo "    nix run .#lint-yaml        # yamllint, actionlint"
    echo "    nix run .#lint-json        # jsonlint, biome, taplo"
    echo "    nix run .#lint-py          # ruff, pyright, mypy, bandit, pylint, vulture"
    echo "    nix run .#lint-nix-files   # nixfmt, statix, deadnix, nil"
    echo "    nix run .#lint-docker      # hadolint"
    echo "    nix run .#lint-md          # markdownlint, mdformat, vale, lychee"
    echo "    nix run .#lint-secrets     # gitleaks, trufflehog, detect-secrets"
    echo "    nix run .#lint-sast        # semgrep, bandit"
    echo "    nix run .#lint-supply      # osv-scanner, trivy, syft"
    echo "    nix run .#lint-spelling    # cspell, typos, codespell"
    echo "    nix run .#lint-extreme     # every lint sequentially"
    echo "    nix run .#everything       # nix flake check + lint-extreme"
    echo "    nix flake check            # gated subset (sandbox-safe only)"
    echo
  '';
}
