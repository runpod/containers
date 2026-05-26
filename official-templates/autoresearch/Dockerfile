ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install runpodctl for pod management (scaling up GPUs)
ARG RUNPODCTL_VERSION=v2.3.0
RUN wget -qO- https://github.com/runpod/runpodctl/releases/download/"${RUNPODCTL_VERSION}"/runpodctl-linux-amd64.tar.gz | \
    tar -xz -C /usr/local/bin runpodctl

# Clone autoresearch to /opt (safe from volume mounts)
ARG AUTORESEARCH_REF=master
RUN git clone --branch "${AUTORESEARCH_REF}" --depth 1 \
    https://github.com/runpod/autoresearch.git /opt/autoresearch

WORKDIR /opt/autoresearch

# Install Python dependencies.
# --frozen: install exactly from uv.lock, no resolver run.
# --locked: assert uv.lock matches pyproject.toml (catches drift at build time).
# --no-build: refuse source distributions — `setup.py` can execute arbitrary
# code during install, and we want only pre-built, audited wheels.
RUN uv sync --frozen --no-build && \
    uv run --frozen --no-build prepare.py # Download data and train tokenizer (~2 min)

# On first boot: copy source files to /workspace (lightweight, persists edits)
# and symlink .venv back to /opt (12GB, stays on fast container layer)
COPY pre_start.sh /pre_start.sh

# Override the NVIDIA CUDA entrypoint which blocks boot on hosts with older
# drivers (e.g. driver 550 only supports CUDA 12.4, but this image has 12.8).
ENTRYPOINT ["/start.sh"]
