<div style="text-align: center;">

<h1> RunPod Base </h1>

</div>

## ⚠️ | Notice

Your development API server is launching, please wait a moment before refreshing the page. Your terminal will say **Starting Serverless Worker** when the server is ready. You might also be seeing this message if your handler has any errors, please check your terminal for more information.

## 🚀 | Usage

Once the server is ready, you will see the list of endpoints available to start sending requests. You can send requests to these endpoints from the FastAPI web interface, a service such as Postman, with cURL or programmatically from a language of your choice.

<!---

# RunPod Base Container Image

This base image is intended to provide the essential runtime system dependencies for most applications. It is by no means optimized and more likely than not includes many packages that you might not need for your use case.

## HuggingFace Cache

This image contains environment variables to override the default HuggingFace cache directory. It will use `/runpod-volume/` as the root path. If you are using network attached storage it is recommended to mount a volume to this path to avoid downloading models on every run.

## Environment Variables

- `POD_INACTIVITY_TIMEOUT`: The number of seconds to wait before shutting down the pod. Defaults to 60 seconds.

## Ports

- **4040**: File Browser
- **7270**: FastAPI Server

## Python Management

- [PyEnv](https://github.com/pyenv/pyenv)
- [VirtualEnv](https://virtualenv.pypa.io/en/latest/index.html)
- [VirtualEnvWrapper](https://virtualenvwrapper.readthedocs.io/en/latest/)
- [uv](https://github.com/astral-sh/uv)

### Building

```bash
docker buildx bake --push
```
-->
