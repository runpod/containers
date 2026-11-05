# `lint-dotenv` — lint .env files. Guarded via maybe-tool.

{ pkgs, lib }:

import ../lib/maybe-tool.nix { inherit pkgs lib; } {
  name = "lint-dotenv";
  tool = pkgs.dotenv-linter or null;
  description = "Run dotenv-linter against tracked .env files.";
  build =
    dotenv-linter:
    import ../lib/mk-lint.nix { inherit pkgs lib; } {
      name = "lint-dotenv";
      description = "Run dotenv-linter against tracked .env files.";
      runtimeInputs = [
        dotenv-linter
        pkgs.git
      ];
      header = "dotenv-linter";
      globs = [
        "*.env"
        ".env*"
        "**/*.env"
      ];
      emptyMessage = "(no .env files tracked)";
      command = ''dotenv-linter "''${files[@]}"'';
    };
}
