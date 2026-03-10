ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

# Clone autoresearch to /opt (safe from volume mounts)
ARG AUTORESEARCH_REF=master
RUN git clone --branch ${AUTORESEARCH_REF} --depth 1 \
    https://github.com/runpod/autoresearch.git /opt/autoresearch

WORKDIR /opt/autoresearch

# Install Python dependencies
RUN uv sync

# Download data and train tokenizer (~2 min)
RUN uv run prepare.py

# On first boot: copy source files to /workspace (lightweight, persists edits)
# and symlink .venv back to /opt (12GB, stays on fast container layer)
COPY pre_start.sh /pre_start.sh
