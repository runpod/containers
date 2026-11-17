# Upstream vLLM pinned by tag + digest in docker-bake.hcl.
ARG VLLM_IMAGE=non-existing
FROM ${VLLM_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --chmod=0644 scripts/runpod_vllm_auth.py /opt/runpod/vllm/runpod_vllm_auth.py
COPY --chmod=0755 scripts/start.sh /start.sh

RUN help="$(vllm serve --help=all 2>&1)" && \
    grep -q -- '--middleware' <<< "$help" && \
    PYTHONPATH=/opt/runpod/vllm python3 -c 'import runpod_vllm_auth'

EXPOSE 8000

ENTRYPOINT ["/start.sh"]
