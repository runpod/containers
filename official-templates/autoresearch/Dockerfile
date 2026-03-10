ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

# Clone autoresearch into workspace
ARG AUTORESEARCH_REF=master
RUN git clone --branch ${AUTORESEARCH_REF} --depth 1 \
    https://github.com/runpod/autoresearch.git /workspace/autoresearch

WORKDIR /workspace/autoresearch

# Install Python dependencies
RUN uv sync

# Download data and train tokenizer (~2 min)
RUN uv run prepare.py
