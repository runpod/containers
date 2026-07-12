# Same image family as family.nix, but built with nix2container instead of
# dockerTools.streamLayeredImage — kept as separate `*-n2c` targets so the two
# layering strategies can be compared head-to-head (see footprint.sh).
#
# nix2container lays out one layer per store path (up to maxLayers) without
# dockerTools' single "customisation layer" collapse, and references store
# paths lazily — so it can carry many layers cheaply and share them maximally
# across images. This is the candidate for closing the 34% -> 53% gap.

{ pkgs, n2c }:

let
  userland = import ./userland.nix { inherit pkgs; };

  # nix2container's copyToRoot strictly merges the paths into one root and
  # errors on collisions (e.g. gawk's /include dir vs the python env's /include
  # symlink). Pre-merge with buildEnv, which tolerates them (first-wins), to
  # match how dockerTools assembled the same contents.
  mkRoot =
    name: contents:
    pkgs.buildEnv {
      name = "runpod-${name}-n2c-root";
      paths = contents;
      ignoreCollisions = true;
    };

  mkImage =
    name: contents:
    n2c.buildImage {
      name = "runpod-${name}-n2c";
      tag = "poc";
      copyToRoot = mkRoot name contents;
      # High on purpose: nix2container references store paths lazily, so many
      # layers are cheap to build (unlike dockerTools, which tars each). At 600
      # every store path gets its own layer, hitting the closure's store-path
      # sharing ceiling (~53% here). At the default (100) it actually shares
      # *less* than dockerTools — see footprint.sh / README.
      maxLayers = 600;
      config = {
        Cmd = [ "/start.sh" ];
        WorkingDir = "/";
        Env = userland.baseEnv ++ [ "PATH=/bin:/usr/bin" ];
      };
    };
in
{
  family-base-n2c = mkImage "family-base" (userland.mkContents { });

  family-data-n2c = mkImage "family-data" (
    userland.mkContents {
      extraPyPackages =
        ps: with ps; [
          numpy
          pandas
          scikit-learn
          matplotlib
          scipy
        ];
    }
  );

  family-serve-n2c = mkImage "family-serve" (
    userland.mkContents {
      extraPyPackages =
        ps: with ps; [
          fastapi
          uvicorn
          pydantic
          pillow
          requests
        ];
    }
  );
}
