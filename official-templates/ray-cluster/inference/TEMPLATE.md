# Ray Cluster Inference (vLLM + LiteLLM)

Serve one Hugging Face model across a whole Runpod Instant Cluster through an OpenAI-compatible API. You configure it with environment variables and don't build an image.

## Description

This template runs `runpod/ray-cluster:<version>-inference-cu1300-torch2130-ubuntu2404`. It's Runpod's Ray cluster image (Ray 2.59.0) with vLLM 0.32.0 behind LiteLLM's proxy. The image starts Ray on every node. The head node waits until all `NUM_NODES` nodes have joined, then serves `MODEL_REPO` with vLLM across the whole cluster. Tensor parallelism is set to the number of GPUs per node and pipeline parallelism to the number of nodes, so a model too large for one machine still runs as a single deployment. LiteLLM's proxy serves the API on port 4000 on the head and requires a key on every request. vLLM itself listens only on `127.0.0.1:8000` and isn't reachable from outside the pod.

The image also includes everything from the base Ray image:
- SSH and Jupyter;
- the Ray dashboard on port 8266;
- Prometheus and Grafana on the head, with vLLM and LiteLLM dashboards in an **Inference** folder alongside the GPU and Ray dashboards.

If vLLM stops, the pod stays up so you can debug it.

## Getting Started

### Dependencies

* A Runpod Instant Cluster, or a single pod, where every node has the same nonzero number of GPUs. This template runs one pipeline stage per node, with tensor parallelism across each node's GPUs.
* A Hugging Face model that vLLM supports and that fits in the cluster's combined GPU memory.
* A Hugging Face token (`HF_TOKEN`) if the model is gated or private.
* An API key. It's `LITELLM_MASTER_KEY` if you set it, otherwise the pod's `JUPYTER_PASSWORD`. If neither is set, the head starts neither vLLM nor LiteLLM.
* A **volume** (not container disk) large enough for the model weights, such as about 470 GB for `Qwen/Qwen3-235B-A22B`. With one network volume shared by every node, the head downloads the model once and the workers reuse it. Without one, each node downloads its own copy. Large models can still take several minutes to load into GPU memory.

### Using the template

* Set the environment variables:

| Variable | Default | Effect |
|---|---|---|
| `MODEL_REPO` | none | The Hugging Face model to serve, such as `Qwen/Qwen3-235B-A22B`. It's also the model name clients send. If it's unset, the head skips vLLM and stays up for interactive use. |
| `HF_TOKEN` | none | Token for gated or private models. |
| `LITELLM_MASTER_KEY` | the head's `JUPYTER_PASSWORD` | Bearer token required on every route of the API. Any string works except well-known defaults such as `sk-1234`. `none` turns authentication off. |
| `MAX_MODEL_LENGTH` | vLLM's default | Passed to vLLM as `--max-model-len`. |
| `VLLM_EXTRA_ARGS` | none | Extra arguments for `vllm serve`. They come after the parallelism settings, so they can override them. `--api-key` is refused. |

* Deploy the cluster and watch the head's logs. Loading takes a while: a minute or more on a multi-node cluster, even for a small model. The API is ready once the log shows:
```
vLLM is ready; starting LiteLLM on 4000
```
* Call the API at `https://<head-pod-id>-4000.proxy.runpod.net` with any OpenAI-compatible client:
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<head-pod-id>-4000.proxy.runpod.net/v1",
    api_key="<LITELLM_MASTER_KEY or JUPYTER_PASSWORD>",
)
reply = client.chat.completions.create(
    model="<MODEL_REPO>",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(reply.choices[0].message.content)
```
* To enable tool calling (`tool_choice: "auto"`), add the vLLM flags. For Qwen3, for example:
```
VLLM_EXTRA_ARGS=--enable-auto-tool-choice --tool-call-parser hermes
```
* Monitoring: Grafana is on port 8889 and the Ray dashboard on 8266. The console links sign you in to both.

## Help

* **502 from the proxy URL on port 4000:** the model is still loading. LiteLLM starts only after vLLM is ready. Check the head's logs for `vLLM is ready`.
* **401:** the request has no key. Send `Authorization: Bearer <key>`.
* **400 "No connected db.":** the key is wrong. LiteLLM runs without a database, so it reports a wrong key this way.
* **400 "\"auto\" tool choice requires --enable-auto-tool-choice…":** tool calling isn't enabled. Add the flags to `VLLM_EXTRA_ARGS` as shown above, then restart the head pod.
* **The head never starts vLLM:** it waits, with no deadline, for all `NUM_NODES` nodes to join Ray, and every node must have the same number of GPUs. Check the worker logs and the Ray dashboard.
* **vLLM exited:** the pod stays up with SSH and Jupyter so you can investigate. Restart the pod to serve again.
* Check that the API is up, from the head (this health route needs no key):
```
curl -s http://127.0.0.1:4000/health/liveliness
```
* Look at vLLM directly, from the head:
```
curl -s http://127.0.0.1:8000/v1/models
```

## Authors

Runpod  
[runpod/containers](https://github.com/runpod/containers)

## Version History

* Initial release
    * vLLM 0.32.0 and LiteLLM 1.108.11 on the Ray cluster image (Ray 2.59.0, CUDA 13.0, PyTorch 2.13, Ubuntu 24.04)
