# Gated derivations consumed by `nix flake check`. These are the
# sandbox-safe checks (no network, no populated language toolchain).
#
# Tools that need network access (osv-scanner, trivy, lychee,
# trufflehog) or a language runtime with resolvable imports
# (pyright/mypy against third-party deps) are exposed as
# `nix run .#lint-*` manual apps only — see ./lints.
#
# Posture is pragmatic: tool defaults, honoring any repo-root config
# file (.yamllint.yaml, .markdownlint.yaml, pyproject.toml, ...).
#
# yamllint and markdownlint are not gated yet: the tree has pre-existing
# findings. Run them with `nix run .#lint-yaml` / `nix run .#lint-md`, and
# move them back here once the tree is clean.

{ pkgs, src }:

let
  mkCheck = import ./lib/mk-check.nix { inherit pkgs src; };
in
{
  # --- Nix (lint our own flake) ---
  nixfmt-check = mkCheck {
    name = "nixfmt-check";
    buildInputs = [
      pkgs.nixfmt
      pkgs.findutils
    ];
    script = ''
      find . -name '*.nix' \
        -not -path './.git/*' \
        -not -path './result*' \
        -exec nixfmt --check {} +
    '';
  };

  deadnix = mkCheck {
    name = "deadnix";
    buildInputs = [
      pkgs.deadnix
      pkgs.findutils
    ];
    script = ''
      find . -name '*.nix' \
        -not -path './.git/*' \
        -not -path './result*' \
        -exec deadnix --fail {} +
    '';
  };

  statix = mkCheck {
    name = "statix";
    buildInputs = [ pkgs.statix ];
    script = "statix check .";
  };

  nil = mkCheck {
    name = "nil";
    buildInputs = [
      pkgs.nil
      pkgs.findutils
    ];
    script = ''
      failed=0
      while IFS= read -r f; do
        diag=$(nil diagnostics "$f" 2>&1) || failed=1
        if [ -n "$diag" ]; then
          printf '=== %s ===\n%s\n' "$f" "$diag"
          failed=1
        fi
      done < <(find . -name '*.nix' \
        -not -path './.git/*' \
        -not -path './result*')
      if [ "$failed" -ne 0 ]; then
        exit 1
      fi
    '';
  };

  # --- Shell ---
  shellcheck = mkCheck {
    name = "shellcheck";
    buildInputs = [
      pkgs.shellcheck
      pkgs.findutils
    ];
    script = ''
      shopt -s nullglob globstar
      mapfile -t shfiles < <(find . \
        -path './.git' -prune -o \
        -path './result*' -prune -o \
        -type f \( -name '*.sh' -o -name '*.bash' \) -print)
      if [ ''${#shfiles[@]} -eq 0 ]; then
        echo "no shell scripts found, skipping"
        exit 0
      fi
      # Match the repo's Shellcheck workflow (fail_level: warning).
      shellcheck -x --severity=warning "''${shfiles[@]}"
    '';
  };

  # --- GitHub Actions ---
  actionlint = mkCheck {
    name = "actionlint";
    buildInputs = [
      pkgs.actionlint
      pkgs.git
    ];
    script = ''
      if [ -d .github/workflows ]; then
        # actionlint finds workflows + reads .github/actionlint.yaml via the
        # git project root; the check sandbox has no .git, so init a throwaway
        # repo to give it one.
        git init -q .
        # Match the repo's Shellcheck workflow (fail_level: warning) for the
        # shellcheck that actionlint runs over `run:` blocks.
        SHELLCHECK_OPTS=--severity=warning actionlint
      fi
    '';
  };

  # --- Docker ---
  hadolint = mkCheck {
    name = "hadolint";
    buildInputs = [
      pkgs.hadolint
      pkgs.findutils
    ];
    script = ''
      mapfile -t df < <(find . \
        -path './.git' -prune -o \
        -type f \( -name 'Dockerfile' -o -name 'Dockerfile.*' -o -name '*.Dockerfile' \) -print)
      if [ ''${#df[@]} -eq 0 ]; then exit 0; fi
      # Match the Hadolint workflows (failure-threshold: warning).
      hadolint -c nix/hadolint.yaml --failure-threshold warning "''${df[@]}"
    '';
  };

  # --- TOML ---
  taplo = mkCheck {
    name = "taplo";
    buildInputs = [
      pkgs.taplo
      pkgs.findutils
    ];
    script = ''
      mapfile -t tf < <(find . \
        -path './.git' -prune -o \
        -type f -name '*.toml' -print)
      if [ ''${#tf[@]} -eq 0 ]; then exit 0; fi
      taplo check "''${tf[@]}"
    '';
  };

  # --- Secrets (no-git working-tree scan; sandbox has no .git) ---
  gitleaks = mkCheck {
    name = "gitleaks";
    buildInputs = [ pkgs.gitleaks ];
    script = "gitleaks detect --no-git --source=. --no-banner --redact";
  };
}
