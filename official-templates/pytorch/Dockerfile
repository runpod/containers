ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN python -m pip install --resume-retries 3 --no-cache-dir --upgrade ${TORCH} --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}

# Verify that the installed torch version matches what was requested.
# pip silently falls back to older versions when wheels are missing from an index,
# which has caused B200 GPUs to be unusable (sm_100 not supported by older PyTorch).
# See: https://github.com/runpod/containers/issues/114
RUN EXPECTED_TORCH=$(echo "${TORCH}" | grep -oP '\btorch==\K[0-9]+\.[0-9]+\.[0-9]+' | head -1) || { \
        echo "ERROR: Could not extract torch version from TORCH='${TORCH}'" >&2; \
        exit 1; \
    } && \
    [ -n "$EXPECTED_TORCH" ] || { \
        echo "ERROR: Extracted torch version is empty from TORCH='${TORCH}'" >&2; \
        exit 1; \
    } && \
    INSTALLED_TORCH=$(python -c "import torch; print(torch.__version__.split('+')[0])") || { \
        echo "ERROR: Failed to determine installed torch version — torch may not be installed." >&2; \
        exit 1; \
    } && \
    [ -n "$INSTALLED_TORCH" ] || { \
        echo "ERROR: Installed torch version string is empty." >&2; \
        exit 1; \
    } && \
    if [ "$EXPECTED_TORCH" != "$INSTALLED_TORCH" ]; then \
        echo "ERROR: PyTorch version mismatch!" >&2; \
        echo "  Expected: ${EXPECTED_TORCH}" >&2; \
        echo "  Installed: ${INSTALLED_TORCH}" >&2; \
        echo "  Wheel source: cu${WHEEL_SRC}" >&2; \
        echo "  Check that wheels exist at: https://download.pytorch.org/whl/cu${WHEEL_SRC}/torch/" >&2; \
        exit 1; \
    fi
