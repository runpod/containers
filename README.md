# Runpod Containers

This repository contains the Dockerfiles for the Runpod containers used for our official templates. Built containers are available on the [Docker Hub](https://hub.docker.com/u/runpod).

## Container Requirements

### Dependencies

The following dependencies are required for all images for Runpod platform functionality.

- `nginx` - Required for proxying ports to the user.
- `openssh-server` - Required for SSH access to the container.
- `jupyterlab` - Required for JupyterLab access to the container.

### README

Every container folder has its own README.md file, this file is displayed on the Docker Hub and the README section of the template on the Runpod website. Additionally, if the container opens a port other than 8888 that is passed through the proxy and the service is not running yet, the README will be displayed to the user to guide them.

## Building Containers

This repository is powered by Docker Buildx and uses [bake files](https://docs.docker.com/build/bake/) to manage builds.

### Using the Bake Script

`./bake.sh` automatically combines shared version definitions with template-specific bake files. 

Use it like this:

```bash
# Build the default targets for a template
./bake.sh base

# Build a specific target or group of targets
./bake.sh base cuda-ubuntu2204-1290

# Build the default targets and load them to the local Docker daemon
./bake.sh base --load
```

### Version Definitions

Version compatibility and build targets for CUDA, Ubuntu, and PyTorch is centralized in `official-templates/shared/versions.hcl`. This file is automatically included when building with the `bake.sh` script. When adding new versions or changing compatibility, modify this file.
