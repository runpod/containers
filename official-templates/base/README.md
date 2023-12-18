# RunPod Base Container Image

This base image is intended to provide the essential runtime system dependencies for most applications. It is by no means optimized and more likely than not includes many packages that you might not need for your use case.

## HuggingFace Cache

This image contains environment variables to override the default HuggingFace cache directory. It will use `/runpod-volume/` as the root path. If you are using network attached storage it is recommended to mount a volume to this path to avoid downloading models on every run.

## Environment Variables

- POD_INACTIVITY_TIMEOUT - The number of seconds to wait before shutting down the pod. Defaults to 60 seconds.

docker buildx bake --push


## Ports

- 4040 - File Browser


## Python Management

https://github.com/pyenv/pyenv

Using:
https://virtualenv.pypa.io/en/latest/index.html

To add:
https://virtualenvwrapper.readthedocs.io/en/latest/
