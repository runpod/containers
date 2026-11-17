# Upstream vLLM pinned by tag + digest in docker-bake.hcl.
ARG VLLM_IMAGE=non-existing
FROM ${VLLM_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --chmod=0644 scripts/runpod_vllm_auth.py /opt/runpod/vllm/runpod_vllm_auth.py
COPY --chmod=0755 scripts/start.sh /start.sh

RUN register="$(python3 -c 'import importlib.util as u; print(u.find_spec("vllm").submodule_search_locations[0])')" && \
    register="$register/entrypoints/serve/middleware/register.py" && \
    { grep -q 'for middleware in args.middleware' "$register" || \
      { echo "vLLM no longer loads --middleware in $register"; exit 1; }; } && \
    PYTHONPATH=/opt/runpod/vllm python3 -c 'import runpod_vllm_auth'

EXPOSE 8000

ENTRYPOINT ["/start.sh"]
