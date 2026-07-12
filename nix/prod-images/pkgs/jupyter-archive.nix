# jupyter-archive 3.4.0 — the one base `requirements.txt` entry not in nixpkgs.
# Built from the PyPI sdist (hash-pinned → narHash) via its hatchling backend.
# It's a JupyterLab extension whose sdist ships the prebuilt JS assets, so no
# node toolchain is needed at build time. If a future bump reintroduces an
# asset build, switch `src` to the wheel (format = "wheel"); the wheel hash is
# sha256-rIViwglxx0Gi3JxcFgoLXSelRwDbl3kGohVJ/S4pEJs=.

{ python, fetchurl }:

python.pkgs.buildPythonPackage {
  pname = "jupyter-archive";
  version = "3.4.0";
  pyproject = true;

  src = fetchurl {
    url = "https://files.pythonhosted.org/packages/6e/8d/2ab96674293cdb333dc90fa9b7a2f4787b3157006624698b44e09e33f3fd/jupyter_archive-3.4.0.tar.gz";
    hash = "sha256-m/AXDgtFrIP8Rsvxq8YPQM7Vqs8LWh2uRl6zvauvF+k=";
  };

  build-system = with python.pkgs; [
    hatchling
    hatch-jupyter-builder
    hatch-nodejs-version
    jupyterlab
  ];

  dependencies = with python.pkgs; [ jupyter-server ];

  # Extension ships prebuilt assets; don't let the jupyter builder try to
  # rebuild them (would need node/jlpm).
  env.HATCH_JUPYTER_BUILDER_SKIP = "1";

  pythonImportsCheck = [ "jupyter_archive" ];
  doCheck = false;

  meta.description = "Jupyter server + lab extension to download folders as archives";
}
