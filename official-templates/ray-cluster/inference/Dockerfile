# The `ray-cluster` inference variant: the ray-cluster image plus vLLM, serving
# one Hugging Face model across every node of the cluster, configured only
# with environment variables (MODEL_REPO, HF_TOKEN, VLLM_API_KEY,
# MAX_MODEL_LENGTH, VLLM_EXTRA_ARGS). See README.md.
#
# Built FROM the ray-cluster target of the same bake run (the `ray-cluster`
# context, see docker-bake.hcl), so it keeps contract v1 with runpod/host
# unchanged: the inherited ENTRYPOINT starts Ray, then runs this image's CMD.

# A bake target context, not a registry image: no tag to pin.
# hadolint ignore=DL3006
FROM ray-cluster

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# vLLM pins torch exactly, so its version must be the one the base was built
# with: 0.32.0 is the last release on torch 2.13.0 (0.33.0 moved to 2.14.0).
# The install is refused if it would replace torch or Ray: torch is the CUDA
# build the base chose, and the host's parsers are pinned to the base's Ray.
# vLLM needs a newer PyJWT than the base's, which is Debian's python3-jwt and
# has no RECORD for pip to uninstall: install the pinned one beside it first
# (pip's copy shadows Debian's on sys.path).
ARG VLLM_VERSION=0.32.0
ARG PYJWT_VERSION=2.15.1
RUN torch_before=$(python -c 'import torch; print(torch.__version__)') && \
    python -m pip install --no-cache-dir --ignore-installed "PyJWT==${PYJWT_VERSION}" && \
    python -m pip install --no-cache-dir "vllm==${VLLM_VERSION}" && \
    torch_after=$(python -c 'import torch; print(torch.__version__)') && \
    ray_after=$(python -c 'import ray; print(ray.__version__)') && \
    { [[ "$torch_after" == "$torch_before" ]] || { echo "vLLM replaced torch $torch_before with $torch_after"; exit 1; }; } && \
    { [[ "$ray_after" == "$RAY_CLUSTER_RAY_VERSION" ]] || { echo "vLLM replaced Ray $RAY_CLUSTER_RAY_VERSION with $ray_after"; exit 1; }; }

COPY --chmod=644 runpod_vllm_auth.py wait_for_nodes.py /opt/runpod/inference/
COPY --chmod=755 start.sh /opt/runpod/inference/start

# The auth middleware rides vLLM's --middleware hook; fail the build if this
# vLLM no longer loads it, rather than serve with routes left open.
RUN register="$(python -c 'import importlib.util as u; print(u.find_spec("vllm").submodule_search_locations[0])')" && \
    register="$register/entrypoints/serve/middleware/register.py" && \
    { grep -q 'for middleware in args.middleware' "$register" || \
      { echo "vLLM no longer loads --middleware in $register"; exit 1; }; } && \
    PYTHONPATH=/opt/runpod/inference python -c 'import runpod_vllm_auth'

# 8000 vLLM's OpenAI-compatible API on the head. Every route except /health,
# /ping and /metrics needs VLLM_API_KEY (else JUPYTER_PASSWORD). Map this one
# in the Runpod template.
EXPOSE 8000

LABEL com.runpod.template.variant="ray-cluster-inference"

# The ENTRYPOINT is inherited and must stay: it starts Ray, then runs this CMD.
CMD ["/opt/runpod/inference/start"]
