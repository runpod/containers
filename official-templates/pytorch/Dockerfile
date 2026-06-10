ARG BASE_IMAGE=non-existing
FROM "${BASE_IMAGE}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG WHEEL_SRC
ARG TORCH

# TORCH is a space-separated list of pip specs (e.g. "torch==2.8.0 torchvision==0.23.0
# torchaudio==2.8.0"). `read -ra` splits it into a real bash array so pip receives one
# argument per package instead of a single mashed-together string.
RUN read -ra TORCH_PKGS <<< "${TORCH}" && \
    python -m pip install \
        --timeout 1000 \
        --retries 10 \
        --resume-retries 5 \
        --no-cache-dir \
        --upgrade \
        "${TORCH_PKGS[@]}" \
        --index-url "https://download.pytorch.org/whl/cu${WHEEL_SRC}"

