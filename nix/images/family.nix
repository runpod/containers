# A small image *family* that all share the common userland, to demonstrate
# cross-image Docker layer sharing (the fleet-caching win). Each member reuses
# the exact same shared store paths for the userland + tools, and only adds its
# own Python stack on top — so those shared layers dedupe on any host that runs
# more than one of them. Measured by ./footprint.sh.
#
# Realistic RunPod-ish flavors, all CPU (so the family builds without GPU):
#   family-base   — the plain base userland
#   family-data   — + a data-science stack (numpy/pandas/scikit-learn/…)
#   family-serve  — + an inference-serving stack (fastapi/uvicorn/pillow/…)

{ pkgs }:

let
  userland = import ./userland.nix { inherit pkgs; };

  mkImage =
    name: contents:
    pkgs.dockerTools.streamLayeredImage {
      name = "runpod-${name}-nix";
      tag = "poc";
      inherit contents;
      config = {
        Cmd = [ "/start.sh" ];
        WorkingDir = "/";
        Env = userland.baseEnv ++ [ "PATH=/bin:/usr/bin" ];
      };
    };
in
{
  family-base = mkImage "family-base" (userland.mkContents { });

  family-data = mkImage "family-data" (
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

  family-serve = mkImage "family-serve" (
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
