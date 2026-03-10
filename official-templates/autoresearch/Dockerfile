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

# Copy to /workspace on first boot (volume mount overlays /workspace at runtime)
RUN echo '#!/bin/bash\nif [ ! -f /workspace/autoresearch/pyproject.toml ]; then\n  cp -a /opt/autoresearch /workspace/autoresearch\nfi' > /pre_start.sh && \
    chmod +x /pre_start.sh
