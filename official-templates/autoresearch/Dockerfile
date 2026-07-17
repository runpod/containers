ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install runpodctl for pod management (scaling up GPUs)
ARG RUNPODCTL_VERSION=v2.3.0
ARG RUNPODCTL_SHA256=908f2210571e8a26a1cba6fb45f09556b34dcad3e1b20dd502df2adf7a57c169
RUN wget -q --https-only --secure-protocol=TLSv1_2 --max-redirect=3 \
    -O /tmp/runpodctl.tar.gz \
    "https://github.com/runpod/runpodctl/releases/download/${RUNPODCTL_VERSION}/runpodctl-linux-amd64.tar.gz" && \
    echo "${RUNPODCTL_SHA256}  /tmp/runpodctl.tar.gz" | sha256sum -c - && \
    tar -xz -C /usr/local/bin -f /tmp/runpodctl.tar.gz runpodctl && \
    rm /tmp/runpodctl.tar.gz

# Clone autoresearch to /opt (safe from volume mounts). Pinned to an immutable
# commit SHA for reproducible builds — `git clone --branch` only accepts a
# branch/tag, so we init + shallow-fetch the exact commit and detach onto it.
# Bump AUTORESEARCH_REF to update.
ARG AUTORESEARCH_REF=d173f4ec6353213bf644631a8d30fa80974cc65f
RUN git init /opt/autoresearch && \
    git -C /opt/autoresearch remote add origin https://github.com/runpod/autoresearch.git && \
    git -C /opt/autoresearch fetch --depth 1 origin "${AUTORESEARCH_REF}" && \
    git -C /opt/autoresearch checkout --detach FETCH_HEAD

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

# PID 1 (ENTRYPOINT tini + CMD /start.sh) is inherited from runpod/base. tini's
# ENTRYPOINT also supersedes the NVIDIA CUDA base entrypoint, which otherwise
# blocks boot on hosts with older drivers (e.g. driver 550 supports only CUDA
# 12.4 while this image ships 12.8) — so no ENTRYPOINT override is needed here.
