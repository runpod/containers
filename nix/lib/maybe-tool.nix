# `maybe-tool` — guard a lint app behind a tool that may be absent from
# the pinned nixpkgs.
#
# A few tools the flake wants may not be packaged in every nixpkgs
# revision. Referencing `pkgs.<missing>` directly aborts evaluation of
# the WHOLE flake (devShell, `nix flake show`, the composites), not just
# that one app. This helper lets a tool file pass `pkgs.<tool> or null`:
# when null, it yields a stand-in app that prints a visible "skipped"
# line and exits 0, so everything else keeps working. When present, it
# builds the real app via `build tool`.
#
# Usage (in nix/lints/<tool>.nix):
#   { pkgs, lib }:
#   import ../lib/maybe-tool.nix { inherit pkgs lib; } {
#     name = "lint-foo";
#     tool = pkgs.foo or null;
#     description = "Run foo against the tree.";
#     build = foo: import ../lib/mk-lint.nix { inherit pkgs lib; } {
#       name = "lint-foo";
#       inherit description;
#       runtimeInputs = [ foo pkgs.git ];
#       command = ''foo .'';
#     };
#   }

{ pkgs, ... }:

{
  name,
  tool,
  description,
  build,
}:

if tool != null then
  build tool
else
  pkgs.writeShellApplication {
    inherit name;
    runtimeInputs = [ ];
    text = ''
      echo "==> ${name}"
      echo "    ${name}: tool not packaged in the pinned nixpkgs — skipped"
    '';
    meta = {
      description = "${description} (unavailable in the current nixpkgs pin)";
      mainProgram = name;
    };
  }
