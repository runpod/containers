# Runpod Containers

This repository contains the Dockerfiles for the Runpod containers used for our official templates. Built containers are available on the [Docker Hub](https://hub.docker.com/u/runpod).

## Container Requirements

### Dependencies

The following dependencies are required for all images for Runpod platform functionality.

- `nginx`: Required for proxying ports to the user.
- `openssh-server`: Required for SSH access to the container.
- `jupyterlab`: Required for JupyterLab access to the container.

### README

Every container folder has its own README.md file, displayed on Docker Hub and in the template section on the Runpod website. When containers open ports other than 8888 through the proxy, the README guides users while services are starting up.

## Building Containers

This repository uses Docker Buildx with [bake files](https://docs.docker.com/build/bake/) to manage builds.

### Using the Bake Script

`./bake.sh` automatically combines shared version definitions with template specific bake files. 

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

Version compatibility and build targets for CUDA, Ubuntu, and PyTorch are centralized in `official-templates/shared/versions.hcl`. This file is automatically included when building with the `bake.sh` script. When adding new versions or changing compatibility, modify this file.
