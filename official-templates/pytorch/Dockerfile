ARG BASE_IMAGE=non-existing
FROM "${BASE_IMAGE}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV NVIDIA_DRIVER_CAPABILITIES=all
ARG WHEEL_SRC
ARG TORCH

# pip steps run through pip-install-layer.sh so identical packages give an
# identical layer. Keep LAYER_EPOCH constant. Mounts live under /tmp or /mnt:
# a mount point BuildKit must create would leave a timestamped dir in the layer.
ARG LAYER_EPOCH=1767225600
# Symlink torch's pip CUDA libs to the base's copies where safe.
ARG DEDUPE_CUDA=true

# TORCH is a space-separated list of pip specs (e.g. "torch==2.8.0
# torchvision==0.23.0"). `read -ra` splits it into a real bash array so pip receives
# one argument per package instead of a single mashed-together string.
RUN --mount=type=tmpfs,target=/tmp \
    --mount=type=cache,id=/root/.cache/pip,target=/tmp/pip-cache,sharing=locked \
    --mount=type=bind,source=.,target=/mnt \
    read -ra TORCH_PKGS <<< "${TORCH}" && \
    dedupe=() && if [ "${DEDUPE_CUDA}" = true ]; then dedupe=(--dedupe-cuda); fi && \
    LAYER_EPOCH="${LAYER_EPOCH}" PIP_CACHE_DIR=/tmp/pip-cache \
    bash /mnt/pip-install-layer.sh "${dedupe[@]}" \
        --timeout 1000 \
        --retries 10 \
        --resume-retries 5 \
        --upgrade \
        "${TORCH_PKGS[@]}" \
        --index-url "https://download.pytorch.org/whl/cu${WHEEL_SRC}"

# torchaudio ended at 2.11.0, so newer CUDA indexes never got it (cu132 stops at
# 2.2.0) and it needs its own index (see audio_index in docker-bake.hcl).
# --no-deps because the wheel declares none and its torch pin must not move this
# build's.
ARG TORCHAUDIO
ARG AUDIO_INDEX
RUN --mount=type=tmpfs,target=/tmp \
    --mount=type=cache,id=/root/.cache/pip,target=/tmp/pip-cache,sharing=locked \
    --mount=type=bind,source=.,target=/mnt \
    if [ -n "${TORCHAUDIO}" ]; then \
        LAYER_EPOCH="${LAYER_EPOCH}" PIP_CACHE_DIR=/tmp/pip-cache \
        bash /mnt/pip-install-layer.sh --no-deps "${TORCHAUDIO}" \
            --index-url "https://download.pytorch.org/whl/${AUDIO_INDEX}"; \
    fi

# torchcodec backs torchaudio.load/save from torch 2.9 on. Its own step because
# its CUDA builds don't track torch's index cadence (see codec_src in
# docker-bake.hcl); --no-deps so it can never pull a different torch.
ARG TORCHCODEC
ARG CODEC_SRC
RUN --mount=type=tmpfs,target=/tmp \
    --mount=type=cache,id=/root/.cache/pip,target=/tmp/pip-cache,sharing=locked \
    --mount=type=bind,source=.,target=/mnt \
    if [ -n "${TORCHCODEC}" ]; then \
        LAYER_EPOCH="${LAYER_EPOCH}" PIP_CACHE_DIR=/tmp/pip-cache \
        bash /mnt/pip-install-layer.sh --no-deps "${TORCHCODEC}" \
            --index-url "https://download.pytorch.org/whl/cu${CODEC_SRC}"; \
    fi

# NIXL (torch 2.15+): the backend behind torch.distributed._transport's
# new_transport("nixl"), for KV-cache / tensor transfer in disaggregated
# inference. NIXL is a space-separated list of pins (see docker-bake.hcl).
# --no-deps: the `nixl` meta package requires BOTH nixl-cu12 and nixl-cu13
# unconditionally, and nixl-cuXX requires an unpinned torch; only the backend
# for this image's CUDA major is wanted, and torch must not move. Its other
# dependency, numpy, is already present through torchvision. The wheel bundles
# its own UCX, so no system packages are needed; RDMA transports additionally
# use the host's ibverbs providers (present in the -cluster image).
ARG NIXL
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    if [ -n "${NIXL}" ]; then \
        read -ra NIXL_PKGS <<< "${NIXL}" && \
        PIP_CACHE_DIR=/root/.cache/pip python -m pip install --no-deps "${NIXL_PKGS[@]}" && \
        python -c "import nixl; from nixl._api import nixl_agent"; \
    fi

# Patched pins for packages that Grype reports as HIGH in the layers above.
COPY --from=requirements requirements.txt /requirements.txt
RUN --mount=type=tmpfs,target=/tmp \
    --mount=type=cache,id=/root/.cache/pip,target=/tmp/pip-cache,sharing=locked \
    --mount=type=bind,source=.,target=/mnt \
    LAYER_EPOCH="${LAYER_EPOCH}" PIP_CACHE_DIR=/tmp/pip-cache \
    bash /mnt/pip-install-layer.sh --upgrade -r /requirements.txt
