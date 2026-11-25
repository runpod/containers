# The `ray-cluster` inference variant: the ray-cluster image plus vLLM, serving
# one Hugging Face model across every node of the cluster behind LiteLLM's
# proxy, configured only with environment variables (MODEL_REPO, HF_TOKEN,
# LITELLM_MASTER_KEY, MAX_MODEL_LENGTH, VLLM_EXTRA_ARGS). See README.md.
#
# Built FROM the ray-cluster target of the same bake run (the `ray-cluster`
# context, see docker-bake.hcl): the inherited ENTRYPOINT starts Ray, then runs
# this image's CMD.

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
# (pip's copy shadows Debian's on sys.path). vLLM's ranged dependencies are
# pinned in requirements.txt; re-resolve it on a vLLM bump.
ARG VLLM_VERSION=0.32.0
ARG PYJWT_VERSION=2.15.1
COPY requirements.txt /tmp/vllm-requirements.txt
RUN torch_before=$(python -c 'import torch; print(torch.__version__)') && \
    python -m pip install --no-cache-dir --ignore-installed "PyJWT==${PYJWT_VERSION}" && \
    python -m pip install --no-cache-dir "vllm==${VLLM_VERSION}" -r /tmp/vllm-requirements.txt && \
    rm /tmp/vllm-requirements.txt && \
    torch_after=$(python -c 'import torch; print(torch.__version__)') && \
    ray_after=$(python -c 'import ray; print(ray.__version__)') && \
    { [[ "$torch_after" == "$torch_before" ]] || { echo "vLLM replaced torch $torch_before with $torch_after"; exit 1; }; } && \
    { [[ "$ray_after" == "$RAY_CLUSTER_RAY_VERSION" ]] || { echo "vLLM replaced Ray $RAY_CLUSTER_RAY_VERSION with $ray_after"; exit 1; }; }

COPY --chmod=644 wait_for_nodes.py download_model.py /opt/runpod/inference/
COPY --chmod=755 start.sh /opt/runpod/inference/start

# LiteLLM's proxy, the API on 4000 (LiteLLM's default) in front of vLLM (which listens on
# 127.0.0.1:8000 only), in its own venv so its pins never touch vLLM's, Ray's
# or torch's. Hash-locked: every package is checked against litellm/
# requirements.txt, whose hashes were taken when the lock was made.
COPY litellm/requirements.txt /tmp/litellm-requirements.txt
RUN python -m venv /opt/litellm && \
    /opt/litellm/bin/pip install --no-cache-dir --require-hashes -r /tmp/litellm-requirements.txt && \
    rm /tmp/litellm-requirements.txt && \
    /opt/litellm/bin/python -c 'import litellm.proxy.proxy_server, prometheus_client'

# vLLM's and LiteLLM's metrics on the head's Prometheus + Grafana: this
# image's post-start hook runs the Ray image's (renamed /post_start.ray.sh),
# then adds their scrape jobs; their example dashboards load into an Inference
# folder.
RUN mv /post_start.sh /post_start.ray.sh
COPY --chmod=755 post_start.sh /post_start.sh
COPY config/provisioning/dashboards/inference.yml /etc/grafana/provisioning/dashboards/inference.yml
COPY config/dashboards/ /opt/runpod/inference/grafana-dashboards/

# The base nginx relays 8001 to localhost:8000 (an unused "vscode server"
# block), which here would be vLLM without LiteLLM's key. #248 removes it from
# the base, but this image builds FROM a published pytorch-cluster that may
# still carry it, so strip it here (a no-op once it's gone) and fail the build
# if anything in nginx still proxies to 8000.
RUN perl -0pi -e 's/(?:^    #[^\n]*\n)?^    server \{\n(?:(?!^    \}\n).)*?proxy_pass http:\/\/(?:localhost|127\.0\.0\.1):8000;(?:(?!^    \}\n).)*^    \}\n\n?//gms' /etc/nginx/nginx.conf && \
    nginx -t && \
    conf=$(nginx -T 2> /dev/null) && \
    { ! grep -Eq 'proxy_pass +https?://[^;]*:8000\b' <<< "$conf" || { echo "nginx still proxies to vLLM's port 8000"; exit 1; }; }

# 4000 the OpenAI-compatible API on the head: LiteLLM, in front of vLLM.
#      Every route except LiteLLM's health checks needs LITELLM_MASTER_KEY
#      (else JUPYTER_PASSWORD). Map this one in the Runpod template. vLLM
#      itself (8000) listens on 127.0.0.1 only.
EXPOSE 4000

LABEL com.runpod.template.variant="ray-cluster-inference"

# The ENTRYPOINT is inherited and must stay: it starts Ray, then runs this CMD.
CMD ["/opt/runpod/inference/start"]
