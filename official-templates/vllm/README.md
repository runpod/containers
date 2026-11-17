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

| Pod environment                  | Result                                                                       |
| -------------------------------- | ---------------------------------------------------------------------------- |
| `VLLM_API_KEY=<secret>`          | vLLM starts. Every request needs `Authorization: Bearer <secret>`, except the probes below. |
| `VLLM_DISABLE_AUTH=true`         | vLLM starts with **no authentication**. Anyone with the URL can use your GPU. |
| Neither                          | vLLM does **not** start. The Logs tab says why, and the Pod stays up so you can fix the env and restart it. |

If both are set, the key wins.

Open without a key: `/health`, `/ping` and `/metrics` (exact paths). Everything else returns `401`, including routes vLLM's own `--api-key` leaves open, such as `/invocations`, `/tokenize` and `/scale_elastic_ep`. A route added in a future vLLM release is closed by default.

The key is never printed to the Pod logs. Do not pass `--api-key` in the container start command: vLLM prints its arguments at startup, so the key would show up in the logs. The image warns if you do.

### Container start command

The start command is passed to `vllm serve`, so anything from the [vLLM serve reference](https://docs.vllm.ai/en/latest/cli/serve.html) works, for example:

```
meta-llama/Llama-3.1-8B-Instruct --max-model-len 16384 --gpu-memory-utilization 0.90
```

The image always appends `--host 0.0.0.0 --port 8000` and its own `--middleware`, so a `--host` or `--port` in the start command has no effect. For gated models, set `HF_TOKEN` in the Pod environment.

### Notes

- The vLLM version is in the image tag: `runpod/vllm-openai:<release>-vllm<vllm-version>`.
- This image runs vLLM only. It has no SSH server or JupyterLab.
- Mooncake is removed, so the Mooncake KV-transfer connectors (multi-node disaggregated serving) are not available.

### Links

- [vLLM documentation](https://docs.vllm.ai/)
- [Source for this image](https://github.com/runpod/containers/tree/main/official-templates/vllm)
