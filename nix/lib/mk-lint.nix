# `mk-lint` — single helper used by every `nix/lints/<tool>.nix`.
#
# Two modes, selected by whether `globs` is provided:
#
#   - **Tree-walk mode** (`globs` omitted or null): the tool walks the
#     working tree itself (e.g. `statix check .`, `typos`, `gitleaks
#     detect`). The body just runs `command` from the repo root.
#
#   - **File-list mode** (`globs` is a list): the helper builds
#     `files=( $(git ls-files <patterns>) )`, exits 0 cleanly when the
#     list is empty, and the per-tool `command` references
#     `"${files[@]}"`.
#
# Inside `command`, escape `$` for shell expansion as `''$` (Nix
# multi-line string convention).

{ pkgs, lib }:

{
  name,
  description,
  runtimeInputs,
  header ? name,
  globs ? null,
  emptyMessage ? "(no matching files tracked)",
  command,
}:

let
  cdRoot = ''cd "$(git rev-parse --show-toplevel)"'';
  banner = ''echo "==> ${header}"'';
  fileList =
    if globs == null then
      ""
    else
      ''
        mapfile -t files < <(git ls-files ${lib.concatStringsSep " " (map (g: "'${g}'") globs)})
        if [ "''${#files[@]}" -eq 0 ]; then
          echo "    ${emptyMessage}"
          exit 0
        fi
      '';
in
pkgs.writeShellApplication {
  inherit name runtimeInputs;
  text = ''
    ${cdRoot}
    ${banner}
    ${fileList}
    ${command}
  '';
  meta.description = description;
}
