ARG BASE_IMAGE=non-existing
FROM "${BASE_IMAGE}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG WHEEL_SRC
ARG TORCH

# TORCH is a space-separated list of pip specs (e.g. "torch==2.8.0 torchvision==0.23.0
# torchaudio==2.8.0"). `read -ra` splits it into a real bash array so pip receives one
# argument per package instead of a single mashed-together string.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    read -ra TORCH_PKGS <<< "${TORCH}" && \
    python -m pip install \
        --timeout 1000 \
        --retries 10 \
        --resume-retries 5 \
        --upgrade \
        "${TORCH_PKGS[@]}" \
        --index-url "https://download.pytorch.org/whl/cu${WHEEL_SRC}"

# torchvision pulls Pillow from the PyTorch wheel index, which lags PyPI and
# ships releases with known HIGH CVEs. Re-install a patched Pillow from PyPI,
# but only when it's already present (torch builds without torchvision have none).
COPY --from=requirements requirements.txt /requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade -r /requirements.txt
