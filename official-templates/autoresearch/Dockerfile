ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install runpodctl for pod management (scaling up GPUs)
ARG RUNPODCTL_VERSION=v2.7.2
ARG RUNPODCTL_SHA256=8216810f9210c3e18c648d828f4d378cdaac0930389b460b1574ff2a3dfd1624
RUN wget -q --https-only --secure-protocol=TLSv1_2 --max-redirect=3 \
    -O /tmp/runpodctl.tar.gz \
    "https://github.com/runpod/runpodctl/releases/download/${RUNPODCTL_VERSION}/runpodctl-linux-amd64.tar.gz" && \
    echo "${RUNPODCTL_SHA256}  /tmp/runpodctl.tar.gz" | sha256sum -c - && \
    tar -xz -C /usr/local/bin -f /tmp/runpodctl.tar.gz runpodctl && \
    rm /tmp/runpodctl.tar.gz

# Clone autoresearch to /opt (safe from volume mounts)
ARG AUTORESEARCH_REF=master
RUN git clone --branch "${AUTORESEARCH_REF}" --depth 1 \
    https://github.com/runpod/autoresearch.git /opt/autoresearch

WORKDIR /opt/autoresearch

# Install Python dependencies.
# --frozen: install exactly from uv.lock, no resolver run.
# --no-build: refuse source distributions — `setup.py` can execute arbitrary code during install, and we want only pre-built, audited wheels.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    export UV_HTTP_TIMEOUT=1000 && \
    uv sync --frozen --no-build && \
    uv run --frozen --no-build prepare.py # Download data and train tokenizer (~2 min)

# On first boot: copy source files to /workspace (lightweight, persists edits)
# and symlink .venv back to /opt (12GB, stays on fast container layer)
COPY pre_start.sh /pre_start.sh

# Override the NVIDIA CUDA entrypoint which blocks boot on hosts with older
# drivers (e.g. driver 550 only supports CUDA 12.4, but this image has 12.8).
ENTRYPOINT ["/start.sh"]
