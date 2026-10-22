ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install FileBrowser Quantum (gtsteffaniak fork), pinned by version + checksum
# so a rebuild reproduces the image. The release ships a static linux-amd64 ELF.
ARG FILEBROWSER_VERSION=v2.0.1-stable
ARG FILEBROWSER_SHA256=42df10b6f2fcd4db17a53f64a9449e677a528164002fd13b050d348d7c477517
RUN wget -q --https-only --secure-protocol=TLSv1_2 --max-redirect=3 \
    -O /usr/local/bin/filebrowser \
    "https://github.com/gtsteffaniak/filebrowser/releases/download/${FILEBROWSER_VERSION}/linux-amd64-filebrowser" && \
    echo "${FILEBROWSER_SHA256}  /usr/local/bin/filebrowser" | sha256sum -c - && \
    chmod +x /usr/local/bin/filebrowser

# Baked config. trustProxyHeaders scopes the session JWT cookie to
# X-Forwarded-Host instead of the pod internal IP, otherwise login breaks
# behind the Runpod proxy.
ENV FILEBROWSER_CONFIG=/etc/filebrowser/config.yaml
COPY config.yaml /etc/filebrowser/config.yaml

# Start FileBrowser alongside the base Jupyter/SSH services on boot.
COPY pre_start.sh /pre_start.sh

# Override the NVIDIA CUDA entrypoint, which blocks boot on hosts with older
# drivers, and fall back to the base start script.
ENTRYPOINT ["/start.sh"]
