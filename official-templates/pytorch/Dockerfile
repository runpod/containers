ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN python -m pip install --resume-retries 3 --no-cache-dir --upgrade ${TORCH} --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}

# Verify that the installed torch version matches what was requested.
# pip silently falls back to older versions when wheels are missing from an index,
# which has caused B200 GPUs to be unusable (sm_100 not supported by older PyTorch).
# See: https://github.com/runpod/containers/issues/114
RUN EXPECTED_TORCH=$(echo "${TORCH}" | grep -oP 'torch==\K[0-9]+\.[0-9]+\.[0-9]+') && \
    INSTALLED_TORCH=$(python -c "import torch; print(torch.__version__.split('+')[0])") && \
    if [ "$EXPECTED_TORCH" != "$INSTALLED_TORCH" ]; then \
        echo "ERROR: PyTorch version mismatch!" >&2; \
        echo "  Expected: ${EXPECTED_TORCH}" >&2; \
        echo "  Installed: ${INSTALLED_TORCH}" >&2; \
        echo "  Wheel source: cu${WHEEL_SRC}" >&2; \
        echo "  Check that wheels exist at: https://download.pytorch.org/whl/cu${WHEEL_SRC}/torch/" >&2; \
        exit 1; \
    fi
