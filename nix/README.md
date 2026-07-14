# Static-analysis flake

A small `flake.nix` at the repo root pulls in the modular `*.nix` files in
this directory to expose a reproducible static-analysis surface for the
`containers` repo: Python, shell, Dockerfiles, YAML / GitHub Actions,
JSON / TOML, Markdown, and the flake's own Nix.

No global installs are needed — every tool is pinned by `flake.lock`.

## Quick start

```sh
# Enter a shell with every tool on PATH (or use direnv + .envrc):
nix develop

# Run the gated, sandbox-safe checks (what CI would gate on):
nix flake check --print-build-logs

# Run a whole domain:
nix run .#lint-py
nix run .#lint-shell
nix run .#lint-docker

# Run absolutely everything:
nix run .#everything
```

## Layout

| Path | Purpose |
| --- | --- |
| `../flake.nix` | Thin entry point: inputs, `src` filter, wires the four modules below, `formatter`. |
| `lib.nix`, `lib/*.nix` | Shared builders: `mk-check` (gated derivations), `mk-lint` (per-tool apps), `mk-all-app` (composites), `maybe-tool` (graceful skip for tools absent from the pin). |
| `checks.nix` | Sandbox-safe derivations for `nix flake check`. |
| `lints/*.nix` | One file per tool + `default.nix` registry + domain composites + `everything.nix`. |
| `devshell/*.nix` | `nix develop` shell carrying every tool. |

## Two execution surfaces

- **`nix flake check`** — gated derivations that run in the Nix sandbox
  (no network, no language runtime with third-party imports): nixfmt,
  statix, deadnix, nil, shellcheck, yamllint, actionlint, hadolint,
  markdownlint, taplo, editorconfig-checker, gitleaks.
- **`nix run .#lint-*`** — manual apps, including tools that need the
  network (trivy, osv-scanner, lychee, trufflehog, semgrep) or the
  project's own dependencies to resolve imports (pyright, pylint).

## Posture

Pragmatic tool defaults, honoring the repo-root config files
(`.yamllint.yaml`, `.markdownlint.yaml`, `pyproject.toml`). Tighten by
editing those configs or the individual `lints/*.nix` commands.

## Known coverage gaps

Some file types in this repo have no first-class linter here and are
left to manual review:

- **HCL** (`docker-bake.hcl`, `versions.hcl`) — no HCL linter is wired
  in; review by hand (or `docker buildx bake --print` to validate).
- **INI** (`grafana.ini`) — only `editorconfig-checker` hygiene applies.
- **CSV** (`extended-counters.csv`) — only `editorconfig-checker`
  hygiene applies.

Large generated JSON (e.g. Grafana dashboards) is validated for
well-formedness by `lint-jsonlint`; deep semantic review is manual.
