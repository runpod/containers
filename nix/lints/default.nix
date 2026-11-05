# Lint registry. flake.nix imports this once per system; we return
# `apps = { ... }` ready for splicing into the flake outputs.
#
# Two layers of composites:
#   - per-domain: lint-shell, lint-yaml, lint-json, lint-py,
#                 lint-nix-files, lint-docker, lint-md, lint-secrets,
#                 lint-sast, lint-supply, lint-spelling
#   - whole-tree: lint-extreme (every per-tool app sequentially)
#                 everything (nix flake check + lint-extreme)
#
# Each per-domain composite re-uses the same `mk-all-app` builder so
# the pass/fail tally format stays consistent.

{ pkgs, lib }:

let
  mkAllApp = import ../lib/mk-all-app.nix { inherit pkgs lib; };

  perTool = lib.mapAttrs (_n: path: import path { inherit pkgs lib; }) {
    # Shell
    lint-shellcheck = ./shellcheck.nix;
    lint-shfmt = ./shfmt.nix;
    lint-bashate = ./bashate.nix;
    lint-checkbashisms = ./checkbashisms.nix;

    # YAML / GitHub Actions
    lint-yamllint = ./yamllint.nix;
    lint-actionlint = ./actionlint.nix;

    # JSON / TOML
    lint-jsonlint = ./jsonlint.nix;
    lint-biome = ./biome.nix;
    lint-taplo = ./taplo.nix;

    # Python
    lint-ruff = ./ruff.nix;
    lint-pyright = ./pyright.nix;
    lint-mypy = ./mypy.nix;
    lint-bandit = ./bandit.nix;
    lint-pylint = ./pylint.nix;
    lint-vulture = ./vulture.nix;

    # Nix
    lint-nixfmt = ./nixfmt.nix;
    lint-statix = ./statix.nix;
    lint-deadnix = ./deadnix.nix;
    lint-nil = ./nil.nix;

    # Docker
    lint-hadolint = ./hadolint.nix;

    # Markdown / prose
    lint-markdown = ./markdown.nix;
    lint-mdformat = ./mdformat.nix;
    lint-lychee = ./lychee.nix;
    lint-vale = ./vale.nix;

    # Hygiene
    lint-editorconfig = ./editorconfig-checker.nix;
    lint-dotenv = ./dotenv-linter.nix;

    # Secrets
    lint-gitleaks = ./gitleaks.nix;
    lint-trufflehog = ./trufflehog.nix;
    lint-detect-secrets = ./detect-secrets.nix;

    # SAST
    lint-semgrep = ./semgrep.nix;

    # Supply chain
    lint-trivy = ./trivy.nix;
    lint-syft = ./syft.nix;
    lint-osv = ./osv-scanner.nix;

    # Spelling
    lint-cspell = ./cspell.nix;
    lint-typos = ./typos.nix;
    lint-codespell = ./codespell.nix;
  };

  pick = names: lib.attrValues (lib.filterAttrs (n: _v: lib.elem n names) perTool);

  mkSubs =
    drvs:
    map (drv: {
      inherit drv;
      binName = drv.meta.mainProgram or drv.name;
    }) drvs;

  mkComposite =
    name: description: drvs:
    mkAllApp {
      inherit name description;
      subs = mkSubs drvs;
    };

  # Domain-grouped composites
  lintShell =
    mkComposite "lint-shell" "All shell lints: shellcheck, shfmt, bashate, checkbashisms."
      (pick [
        "lint-shellcheck"
        "lint-shfmt"
        "lint-bashate"
        "lint-checkbashisms"
      ]);
  lintYaml = mkComposite "lint-yaml" "YAML + Actions: yamllint, actionlint." (pick [
    "lint-yamllint"
    "lint-actionlint"
  ]);
  lintJson = mkComposite "lint-json" "JSON/TOML: jsonlint (validate), biome, taplo." (pick [
    "lint-jsonlint"
    "lint-biome"
    "lint-taplo"
  ]);
  lintPy =
    mkComposite "lint-py" "All Python lints: ruff, pyright, mypy, bandit, pylint, vulture."
      (pick [
        "lint-ruff"
        "lint-pyright"
        "lint-mypy"
        "lint-bandit"
        "lint-pylint"
        "lint-vulture"
      ]);
  lintNixFiles = mkComposite "lint-nix-files" "Nix lints: nixfmt, statix, deadnix, nil." (pick [
    "lint-nixfmt"
    "lint-statix"
    "lint-deadnix"
    "lint-nil"
  ]);
  lintDocker = mkComposite "lint-docker" "Dockerfile lints: hadolint." (pick [ "lint-hadolint" ]);
  lintMd = mkComposite "lint-md" "Markdown + prose: markdownlint, mdformat, vale, lychee." (pick [
    "lint-markdown"
    "lint-mdformat"
    "lint-vale"
    "lint-lychee"
  ]);
  lintSecrets = mkComposite "lint-secrets" "Secrets: gitleaks, trufflehog, detect-secrets." (pick [
    "lint-gitleaks"
    "lint-trufflehog"
    "lint-detect-secrets"
  ]);
  lintSast = mkComposite "lint-sast" "SAST: semgrep, bandit." (pick [
    "lint-semgrep"
    "lint-bandit"
  ]);
  lintSupply = mkComposite "lint-supply" "Supply chain: osv-scanner, trivy, syft." (pick [
    "lint-osv"
    "lint-trivy"
    "lint-syft"
  ]);
  lintSpelling = mkComposite "lint-spelling" "Spelling: cspell, typos, codespell." (pick [
    "lint-cspell"
    "lint-typos"
    "lint-codespell"
  ]);

  lintExtreme = mkAllApp {
    name = "lint-extreme";
    subs = lib.mapAttrsToList (n: drv: {
      inherit drv;
      binName = n;
    }) perTool;
    description = "Run every manual lint sequentially; tally pass/fail.";
  };

  everything = import ./everything.nix { inherit pkgs; };

  composites = {
    lint-shell = lintShell;
    lint-yaml = lintYaml;
    lint-json = lintJson;
    lint-py = lintPy;
    lint-nix-files = lintNixFiles;
    lint-docker = lintDocker;
    lint-md = lintMd;
    lint-secrets = lintSecrets;
    lint-sast = lintSast;
    lint-supply = lintSupply;
    lint-spelling = lintSpelling;
    lint-extreme = lintExtreme;
    inherit everything;
  };

  allLints = perTool // composites;

  drvsToApps = lib.mapAttrs (
    name: drv: {
      type = "app";
      program = "${drv}/bin/${name}";
      meta = drv.meta or { };
    }
  );
in
{
  apps = drvsToApps allLints;
  drvs = allLints;
}
