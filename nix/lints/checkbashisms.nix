# `lint-checkbashisms` — flag bashisms in scripts that claim POSIX sh.
# Guarded via maybe-tool: not packaged in every nixpkgs pin.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-checkbashisms";
  tool = pkgs.checkbashisms or null;
  description = "Run checkbashisms against tracked shell files.";
  build =
    checkbashisms:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-checkbashisms";
      description = "Run checkbashisms against tracked shell files.";
      runtimeInputs = [
        checkbashisms
        pkgs.git
      ];
      header = "checkbashisms";
      globs = [
        "*.sh"
        "*.bash"
      ];
      emptyMessage = "(no shell files tracked)";
      command = ''checkbashisms "''${files[@]}"'';
    };
}
