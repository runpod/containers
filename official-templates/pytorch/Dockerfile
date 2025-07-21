ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN python3.10 -m pip install --resume-retries 3 --no-cache-dir --upgrade ${TORCH} --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}
