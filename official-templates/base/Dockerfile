ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}


RUN groupadd -r nonroot \
    && useradd -r -g nonroot nonroot


USER nonroot

ARG RP_SKIP_PYTHON
ARG RP_SKIP_JUPYTER

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV PYTHONUNBUFFERED=True
ENV DEBIAN_FRONTEND=noninteractive

# Set the default workspace directory
ENV RP_WORKSPACE=/workspace

# Override the default huggingface cache directory.
ENV HF_HOME="${RP_WORKSPACE}/.cache/huggingface/"

# Shared python package cache
ENV VIRTUALENV_OVERRIDE_APP_DATA="${RP_WORKSPACE}/.cache/virtualenv/"
ENV PIP_CACHE_DIR="${RP_WORKSPACE}/.cache/pip/"
ENV UV_CACHE_DIR="${RP_WORKSPACE}/.cache/uv/"

# Faster transfer of models from the hub to the container
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV HF_XET_HIGH_PERFORMANCE=1

# modern pip workarounds
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_ROOT_USER_ACTION=ignore

# Set TZ and Locale
ENV TZ=Etc/UTC

WORKDIR /

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends \
    build-essential ca-certificates cifs-utils cmake curl dirmngr dnsutils ffmpeg \
    file gfortran git gpg gpg-agent inetutils-traceroute inotify-tools iputils-ping jq \
    libatlas-base-dev libavcodec-dev libavfilter-dev libavformat-dev libblas-dev libffi-dev \
    libgl1 libhdf5-dev libjpeg-dev liblapack-dev libnuma-dev libpng-dev libpostproc-dev \
    libsm6 libssl-dev libswscale-dev libtiff-dev libv4l-dev libx264-dev libxrender-dev \
    libxvidcore-dev lsof make mtr nano nfs-common nginx openssh-server rsync slurm-wlm \
    software-properties-common sudo tmux unzip vim wget zip zstd && \
    rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
    rm -rf /var/lib/apt/lists/*
    
# Strip AWS EFA Nsight plugin — AWS-only hardware, not used on RunPod.
# Its nic_sampler Go binary ships old Go stdlib that triggers HIGH Trivy CVEs.
RUN find /opt/nvidia /usr/local/cuda* -type d -name 'efa_metrics' \
        -print -exec rm -rf {} + 2>/dev/null || true

# Install Python versions
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get install --yes --no-install-recommends \
        python3.9-dev python3.9-venv python3.9-distutils \
        python3.10-dev python3.10-venv python3.10-distutils \
        python3.11-dev python3.11-venv python3.11-distutils \
        python3.12-dev python3.12-venv \
        python3.13-dev python3.13-venv && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*;

# Install pip via verified get-pip.py
ARG GET_PIP_COMMIT=0d4515b4d114f9cd820446a4bd4bd0986393d454
ARG GET_PIP_SHA256=66904bccb878e363db6236ea900e6935e507dcb887e9f178f6212edfe7f46a76
ARG GET_PIP_39_SHA256=95c0ae79ccf9ac1e47e4187f49081d6ae1f45997afd4549e14f37337cbcfd766
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    curl -fsSL -o /tmp/get-pip.py \
        "https://raw.githubusercontent.com/pypa/get-pip/${GET_PIP_COMMIT}/public/get-pip.py" && \
    echo "${GET_PIP_SHA256}  /tmp/get-pip.py" | sha256sum -c - && \
    curl -fsSL -o /tmp/get-pip-3.9.py \
        "https://raw.githubusercontent.com/pypa/get-pip/${GET_PIP_COMMIT}/public/3.9/get-pip.py" && \
    echo "${GET_PIP_39_SHA256}  /tmp/get-pip-3.9.py" | sha256sum -c - && \
    python3.9  /tmp/get-pip-3.9.py && \
    python3.10 /tmp/get-pip.py && \
    python3.11 /tmp/get-pip.py && \
    python3.12 /tmp/get-pip.py && \
    python3.13 /tmp/get-pip.py && \
    rm /tmp/get-pip.py /tmp/get-pip-3.9.py

# Install virtualenv
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    python3.9 -m pip install --upgrade --no-cache-dir pip virtualenv && \
    python3.10 -m pip install --upgrade --no-cache-dir pip virtualenv && \
    python3.11 -m pip install --upgrade --no-cache-dir pip virtualenv && \
    python3.12 -m pip install --upgrade --no-cache-dir pip virtualenv && \
    python3.13 -m pip install --upgrade --no-cache-dir pip virtualenv;

# Symlink default python/pip
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python && \
    ln -sf /usr/local/bin/pip3.12 /usr/local/bin/pip && \
    ln -sf /usr/local/bin/pip3.12 /usr/local/bin/pip3;

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY --from=requirements requirements.txt /requirements.txt
COPY --from=scrab_stale_metadata scrub-stale-metadata.py /tmp/scrub-stale-metadata.py

# Install Jupyter and hf_transfer packages
RUN [[ -n "$RP_SKIP_JUPYTER" ]] && exit 0; \
    python -m pip install --upgrade --no-cache-dir -r requirements.txt && \
    python /tmp/scrub-stale-metadata.py /requirements.txt && \
    rm /tmp/scrub-stale-metadata.py

# Install filebrowser (pinned + SHA-256 verified, avoids `curl | bash`).
# Bump FILEBROWSER_VERSION + FILEBROWSER_SHA256 together when updating.
# Checksums: https://github.com/filebrowser/filebrowser/releases
ARG FILEBROWSER_VERSION=2.63.5
ARG FILEBROWSER_SHA256=b36ad6296db0a749a5adbc792ab5321d11b307106123d44e171b7c158fcca2d9
RUN curl -fsSL -o /tmp/filebrowser.tar.gz \
        "https://github.com/filebrowser/filebrowser/releases/download/v${FILEBROWSER_VERSION}/linux-amd64-filebrowser.tar.gz" && \
    echo "${FILEBROWSER_SHA256}  /tmp/filebrowser.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/filebrowser.tar.gz -C /usr/local/bin filebrowser && \
    chmod +x /usr/local/bin/filebrowser && \
    rm /tmp/filebrowser.tar.gz

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy snippets /etc/nginx/snippets
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Script
COPY --from=scripts --chmod=755 start.sh /

# Welcome Message
COPY --from=logo runpod.txt /etc/runpod.txt
RUN cat >> /root/.bashrc <<'EOF'
cat /etc/runpod.txt
printf "%s" "\nFor detailed documentation and guides, please visit:\n\
https://docs.runpod.io/\n\
and https://blog.runpod.io\n\n"
EOF

CMD ["/start.sh"]