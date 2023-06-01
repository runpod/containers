# RunPod Containers

This repository contains the Dockerfiles for the RunPod containers used for our official templates. Resulting containers are available on [Docker Hub](https://hub.docker.com/u/runpod).

## Changes

The containers `serverless-automatic` and `sd-auto-abdbarho` have been removed from this repository. The worker replacement can be found in the [runpod-workers/worker-a1111](https://github.com/runpod-workers/worker-a1111) repository.

## Container Requirements

### README

Every container folder needs to have its own README.md file, this file will be displayed both on the Docker Hub as well as the README section of the template on the RunPod website. Additionally, if the container is opening a port other than 8888 that is passed through the proxy and the service is not running yet, the README will be displayed to the user.

## Building Containers

docker build should be ran from the root of the repository, not from the container folder. The build command should be ran as follows:

```bash
docker build -t runpod/<container-name>:<version> -f <container-name>/Dockerfile .
```
