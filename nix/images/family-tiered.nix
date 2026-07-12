# Explicit-tiering family (nix2container): instead of relying on per-store-path
# auto-layering (which needs ~275 layers/image to hit the sharing ceiling), put
# the ENTIRE shared userland into one explicit `buildLayer` that every image
# reuses byte-for-byte, and give each flavor only a small delta on top.
#
# Goal: near-ceiling sharing at a LOW layer count. All three images reference
# the same `sharedLayer` derivation => identical digest => one cached blob;
# store paths already in it are not duplicated in a flavor's delta.
#
# Kept as separate `*-tiered` targets so the dockerTools and auto-layered n2c
# families remain for comparison (see footprint.sh).

{ pkgs, n2c }:

let
  userland = import ./userland.nix { inherit pkgs; };

  baseContents = userland.mkContents { };

  # One shared layer holding the whole base-userland closure (tools + base
  # python env). buildLayer defaults to a single layer; every image below
  # includes this same derivation, so it dedupes to one blob across the family.
  sharedLayer = n2c.buildLayer { deps = baseContents; };

  mkImage =
    name: contents:
    n2c.buildImage {
      name = "runpod-${name}-tiered";
      tag = "poc";
      layers = [ sharedLayer ];
      copyToRoot = pkgs.buildEnv {
        name = "runpod-${name}-tiered-root";
        paths = contents;
        ignoreCollisions = true;
      };
      # Small delta budget: paths already in sharedLayer are not re-added, so
      # only a flavor's extra packages land here.
      maxLayers = 20;
      config = {
        Cmd = [ "/start.sh" ];
        WorkingDir = "/";
        Env = userland.baseEnv ++ [ "PATH=/bin:/usr/bin" ];
      };
    };
in
{
  family-base-tiered = mkImage "family-base" baseContents;

  family-data-tiered = mkImage "family-data" (
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

  family-serve-tiered = mkImage "family-serve" (
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
