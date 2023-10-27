# RunPod Base Container Image

This base image is intended to provide the essential runtime system dependencies for most applications. It is by no means optimized and more likely than not includes many packages that you might not need for your use case.

## HuggingFace Cache

This image contains environment variables to override the default HuggingFace cache directory. It will use `/runpod-volume/` as the root path. If you are using network attached storage it is recommended to mount a volume to this path to avoid downloading models on every run.
