# jupyter-archive, the one official-templates/base/requirements.txt entry
# nixpkgs doesn't package. Built from the PyPI sdist, which ships the prebuilt
# JupyterLab assets, so no node toolchain is needed. Bump version + hash with
# requirements.txt.

{
  buildPythonPackage,
  fetchurl,
  hatchling,
  hatch-jupyter-builder,
  hatch-nodejs-version,
  jupyterlab,
  jupyter-server,
}:

buildPythonPackage {
  pname = "jupyter-archive";
  version = "3.4.0";
  pyproject = true;

  src = fetchurl {
    url = "https://files.pythonhosted.org/packages/6e/8d/2ab96674293cdb333dc90fa9b7a2f4787b3157006624698b44e09e33f3fd/jupyter_archive-3.4.0.tar.gz";
    hash = "sha256-m/AXDgtFrIP8Rsvxq8YPQM7Vqs8LWh2uRl6zvauvF+k=";
  };

  build-system = [
    hatchling
    hatch-jupyter-builder
    hatch-nodejs-version
    jupyterlab
  ];

  dependencies = [ jupyter-server ];

  # The sdist already has the built assets; don't rebuild them with jlpm.
  env.HATCH_JUPYTER_BUILDER_SKIP = "1";

  pythonImportsCheck = [ "jupyter_archive" ];

  meta.description = "Jupyter server + lab extension to download folders as archives";
}
