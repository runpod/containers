#Note: Two configurable environment variables must be user-specified: HF_MODEL specifies what model to download and serve, HF_TOKEN optionally lets you add your huggingface credential to access gated models
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN python -m pip install --resume-retries 3 --no-cache-dir --upgrade ${TORCH} --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}
RUN python -m pip install vllm
RUN python -m pip install "ray[default]"

COPY pre_start.sh /pre_start.sh
