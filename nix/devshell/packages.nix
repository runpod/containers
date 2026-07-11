# Union of all tool binaries used by `nix run .#lint-*` apps and the
# gated `nix flake check` derivations. A contributor with `nix develop`
# can run any tool directly.
#
# A few tools are not packaged in every nixpkgs pin; `attr or null`
# keeps the shell evaluating and we filter the nulls out below. Their
# lint apps degrade to a visible skip via ../lib/maybe-tool.nix.

{ pkgs }:

let
  optional = builtins.filter (p: p != null) [
    (pkgs.bashate or null)
    (pkgs.checkbashisms or null)
    (pkgs.vulture or pkgs.python3Packages.vulture or null)
    (pkgs.python3Packages.mdformat or null)
    (pkgs.vale or null)
    (pkgs.dotenv-linter or null)
    (pkgs.detect-secrets or pkgs.python3Packages.detect-secrets or null)
    (pkgs.cspell or null)
  ];
in
optional
++ (with pkgs; [
  # Core
  git
  bash
  gnugrep
  coreutils
  findutils
  python3

  # Shell
  shellcheck
  shfmt

  # YAML / Actions
  yamllint
  actionlint

  # JSON / TOML
  biome
  taplo

  # Python
  ruff
  pyright
  mypy
  bandit
  pylint

  # Nix
  nixfmt-rfc-style
  statix
  deadnix
  nil

  # Docker
  hadolint

  # Markdown / prose
  markdownlint-cli2
  lychee

  # Hygiene
  editorconfig-checker

  # Secrets
  gitleaks
  trufflehog

  # SAST / vuln / supply chain
  semgrep
  osv-scanner
  trivy
  syft

  # Spelling
  typos
  codespell
])
