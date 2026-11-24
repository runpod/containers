### Runpod vLLM

**An OpenAI-compatible LLM server powered by [vLLM](https://github.com/vllm-project/vllm), with an API key required on every route.**

The upstream [`vllm/vllm-openai`](https://hub.docker.com/r/vllm/vllm-openai) image, pinned to a release, plus an entrypoint and an authentication middleware.

### Getting started

1. Deploy a Pod from this template. Port `8000/http` is exposed.
2. Set **`VLLM_API_KEY`** in the Pod's environment variables to a long random secret. Without it, vLLM does not start. See [Authentication](#authentication).
3. Pick the model and serving flags in **Container Start Command** (default: `Qwen/Qwen3-8B --dtype auto ...`). Startup downloads the model to `/workspace/.huggingface` and loads it, which takes several minutes. Follow it in the Pod's **Logs** tab.
4. Call the server at `https://<pod-id>-8000.proxy.runpod.net`:

```bash
curl https://<pod-id>-8000.proxy.runpod.net/v1/chat/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-8B", "messages": [{"role": "user", "content": "Hello"}]}'
```

Any OpenAI SDK works, with `base_url="https://<pod-id>-8000.proxy.runpod.net/v1"` and `api_key=<VLLM_API_KEY>`.

### Authentication

`VLLM_API_KEY` is required. With it set, every request needs `Authorization: Bearer <VLLM_API_KEY>`, except the probes below. Without it, vLLM does **not** start: the Logs tab says why, and the Pod stays up so you can set the variable and restart it. There is no way to run this image without authentication.

Open without a key: `/health`, `/ping` and `/metrics` (exact paths). Everything else returns `401`, including routes vLLM's own `--api-key` leaves open, such as `/invocations`, `/tokenize` and `/scale_elastic_ep`. A route added in a future vLLM release is closed by default.

The key is never printed to the Pod logs. Do not set `--api-key` in the container start command, in any spelling or in a `--config` file: vLLM's own `/v1` check would then use a second key, and it prints its arguments at startup. If you do, vLLM is not started and the Logs tab says why.

### Container start command

The start command is passed to `vllm serve`, so anything from the [vLLM serve reference](https://docs.vllm.ai/en/latest/cli/serve.html) works, for example:

```
meta-llama/Llama-3.1-8B-Instruct --max-model-len 16384 --gpu-memory-utilization 0.90
```

The image always appends `--host 0.0.0.0 --port 8000` and its own `--middleware`, so a `--host` or `--port` in the start command has no effect. For gated models, set `HF_TOKEN` in the Pod environment.

With an empty start command vLLM is not started (it would exit with no model); the Logs tab says so and the Pod stays up.

### Notes

- The vLLM version is in the image tag: `runpod/vllm-openai:<release>-vllm<vllm-version>`.
- SSH: the Pod's **Connect** button works with a key from your Runpod account (`PUBLIC_KEY`), password login is disabled. SSH sessions do not see the Pod's environment variables, so `VLLM_API_KEY` stays out of shells. There is no JupyterLab.
- Models are cached in `HF_HOME=/workspace/.huggingface`, on the Pod volume, so a restart does not download them again.
- Mooncake is removed, so the Mooncake KV-transfer connectors (multi-node disaggregated serving) are not available.
- PyNvVideoCodec is removed, so `VLLM_VIDEO_LOADER_BACKEND=pynvvideocodec` (GPU video decoding) is not available. The default `opencv` video backend is unaffected.

### Links

- [vLLM documentation](https://docs.vllm.ai/)
- [Source for this image](https://github.com/runpod/containers/tree/main/official-templates/vllm)
