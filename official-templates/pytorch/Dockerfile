ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install \
        --timeout 1000 \
        --retries 10 \
        --resume-retries 5 \
        --upgrade \
        ${TORCH} \
        --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}
