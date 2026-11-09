# Static-analysis flake

A small `flake.nix` at the repo root pulls in the modular `*.nix` files in
this directory to expose a reproducible static-analysis surface for the
`containers` repo: Python, shell, Dockerfiles, YAML / GitHub Actions,
JSON / TOML, Markdown, and the flake's own Nix.

No global installs are needed — every tool is pinned by `flake.lock`.

## Install Nix on macOS

Tested on Apple Silicon (macOS 27.2) with Determinate Nix 2.35.

1. Install [Determinate Nix](https://docs.determinate.systems/getting-started):
   either the signed graphical installer, `Determinate.pkg` from
   [install.determinate.systems](https://install.determinate.systems), or:

   ```sh
   curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix \
     | sh -s -- install --determinate
   ```

   It puts `/nix` on its own APFS volume, which survives macOS updates,
   and turns flakes on. Open a new terminal and check with `nix --version`.
   To remove it: `/nix/nix-installer uninstall`.
2. Optional: load the dev shell automatically on `cd` with direnv.

   ```sh
   brew install direnv
   echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
   # then, in a new terminal, at the repo root:
   direnv allow
   ```

3. Run the [quick start](#quick-start) below.

On macOS, everything in this harness works: the checks, `nix develop` and
the `lint-*` apps. The container images are Linux-only (`x86_64-linux`),
so build them on Linux or through a Linux remote builder.

With the upstream installer from nixos.org instead, enable flakes first:
add `experimental-features = nix-command flakes` to
`~/.config/nix/nix.conf`.

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
| `../flake.nix` | Thin entry point: nixpkgs (channel tarball), systems, `src` filter, wires the modules below, `formatter`. |
| `lib.nix`, `lib/*.nix` | Shared builders: `mk-check` (gated derivations), `mk-lint` (per-tool apps), `mk-all-app` (composites), `maybe-tool` (graceful skip for tools absent from the pin). |
| `checks.nix` | Sandbox-safe derivations for `nix flake check`. |
| `lints/*.nix` | One file per tool + `default.nix` registry + domain composites + `everything.nix`. |
| `devshell/*.nix` | `nix develop` shell carrying every tool. |
| `images/` | Nix-built counterparts of the base/pytorch/rocm images; see [images/README.md](images/README.md). |

## Two execution surfaces

- **`nix flake check`** — gated derivations that run in the Nix sandbox
  (no network, no language runtime with third-party imports): nixfmt,
  statix, deadnix, nil, shellcheck, actionlint, hadolint, taplo, gitleaks.
  shellcheck and hadolint fail at `warning`, as the repo's workflows do;
  hadolint reads `nix/hadolint.yaml`. yamllint and markdownlint aren't
  gated yet because the tree has pre-existing findings; run them with
  `nix run .#lint-yaml` and `nix run .#lint-md`. editorconfig-checker
  isn't gated because the repo has no `.editorconfig` for it to check.
- **`nix run .#lint-*`** — manual apps, including tools that need the
  network (trivy, osv-scanner, lychee, trufflehog) or the
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
- **INI** (`grafana.ini`) and **CSV** (`extended-counters.csv`) — none;
  `editorconfig-checker` would cover whitespace once there's an
  `.editorconfig`.

Large generated JSON (e.g. Grafana dashboards) is validated for
well-formedness by `lint-jsonlint`; deep semantic review is manual.
