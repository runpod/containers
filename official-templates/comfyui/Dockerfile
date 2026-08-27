# ============================================================================
# Stage 1: Builder - Download pinned sources and install all Python packages
# ============================================================================
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# ---- Version pins (set in docker-bake.hcl) ----
ARG COMFYUI_VERSION
ARG MANAGER_SHA
ARG KJNODES_SHA
ARG CIVICOMFY_SHA
ARG RUNPODDIRECT_SHA
ARG TORCH_VERSION
ARG TORCHVISION_VERSION
ARG TORCHAUDIO_VERSION

# ---- CUDA variant (set in docker-bake.hcl per target) ----
ARG CUDA_VERSION_DASH=12-8
ARG TORCH_INDEX_SUFFIX=cu128

# Install minimal dependencies needed for building
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    curl \
    git \
    ca-certificates \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    build-essential \
    && wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb \
    && dpkg -i cuda-keyring_1.1-1_all.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends cuda-minimal-build-${CUDA_VERSION_DASH} libcusparse-dev-${CUDA_VERSION_DASH} \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm cuda-keyring_1.1-1_all.deb \
    && rm -f /usr/lib/python3.12/EXTERNALLY-MANAGED

# Install pip and pip-tools for lock file generation.
RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.12 get-pip.py "pip==26.1.2" && \
    python3.12 -m pip install --no-cache-dir "pip-tools==7.6.0" && \
    rm get-pip.py

# Set CUDA environment for building
ENV PATH=/usr/local/cuda/bin:${PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64

# Download pinned source archives
WORKDIR /tmp/build
RUN curl -fSL "https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/${COMFYUI_VERSION}.tar.gz" -o comfyui.tar.gz && \
    mkdir -p ComfyUI && tar xzf comfyui.tar.gz --strip-components=1 -C ComfyUI && rm comfyui.tar.gz

WORKDIR /tmp/build/ComfyUI/custom_nodes
RUN curl -fSL "https://github.com/ltdrdata/ComfyUI-Manager/archive/${MANAGER_SHA}.tar.gz" -o manager.tar.gz && \
    mkdir -p ComfyUI-Manager && tar xzf manager.tar.gz --strip-components=1 -C ComfyUI-Manager && rm manager.tar.gz && \
    curl -fSL "https://github.com/kijai/ComfyUI-KJNodes/archive/${KJNODES_SHA}.tar.gz" -o kjnodes.tar.gz && \
    mkdir -p ComfyUI-KJNodes && tar xzf kjnodes.tar.gz --strip-components=1 -C ComfyUI-KJNodes && rm kjnodes.tar.gz && \
    curl -fSL "https://github.com/MoonGoblinDev/Civicomfy/archive/${CIVICOMFY_SHA}.tar.gz" -o civicomfy.tar.gz && \
    mkdir -p Civicomfy && tar xzf civicomfy.tar.gz --strip-components=1 -C Civicomfy && rm civicomfy.tar.gz && \
    curl -fSL "https://github.com/MadiatorLabs/ComfyUI-RunpodDirect/archive/${RUNPODDIRECT_SHA}.tar.gz" -o runpoddirect.tar.gz && \
    mkdir -p ComfyUI-RunpodDirect && tar xzf runpoddirect.tar.gz --strip-components=1 -C ComfyUI-RunpodDirect && rm runpoddirect.tar.gz

# Init git repos with upstream remotes so ComfyUI-Manager can detect versions
# and users can update via Manager at their own risk
RUN cd /tmp/build/ComfyUI && \
    git init && git add -A && git -c user.name=- -c user.email=- commit -q -m "ComfyUI ${COMFYUI_VERSION}" && git tag "${COMFYUI_VERSION}" && \
    git remote add origin https://github.com/comfyanonymous/ComfyUI.git && \
    cd /tmp/build/ComfyUI/custom_nodes/ComfyUI-Manager && \
    git init && git add -A && git -c user.name=- -c user.email=- commit -q -m "ComfyUI-Manager ${MANAGER_SHA}" && \
    git remote add origin https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd /tmp/build/ComfyUI/custom_nodes/ComfyUI-KJNodes && \
    git init && git add -A && git -c user.name=- -c user.email=- commit -q -m "ComfyUI-KJNodes ${KJNODES_SHA}" && \
    git remote add origin https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd /tmp/build/ComfyUI/custom_nodes/Civicomfy && \
    git init && git add -A && git -c user.name=- -c user.email=- commit -q -m "Civicomfy ${CIVICOMFY_SHA}" && \
    git remote add origin https://github.com/MoonGoblinDev/Civicomfy.git && \
    cd /tmp/build/ComfyUI/custom_nodes/ComfyUI-RunpodDirect && \
    git init && git add -A && git -c user.name=- -c user.email=- commit -q -m "ComfyUI-RunpodDirect ${RUNPODDIRECT_SHA}" && \
    git remote add origin https://github.com/MadiatorLabs/ComfyUI-RunpodDirect.git

# Generate lock file from all requirements (including torch pins), then install with hash verification
WORKDIR /tmp/build
RUN cat ComfyUI/requirements.txt > requirements.in && \
    for node_dir in ComfyUI/custom_nodes/*/; do \
        if [ -f "$node_dir/requirements.txt" ]; then \
            cat "$node_dir/requirements.txt" >> requirements.in; \
        fi; \
    done && \
    echo "GitPython" >> requirements.in && \
    echo "opencv-python" >> requirements.in && \
    echo "jupyter" >> requirements.in && \
    echo "jupyter-resource-usage" >> requirements.in && \
    echo "jupyterlab-nvdashboard" >> requirements.in && \
    sed -i -E '/^[[:space:]]*(torch|torchvision|torchaudio)([[:space:]]|[\[<>=!~;#]|$)/d' requirements.in && \
    echo "torch==${TORCH_VERSION}" >> requirements.in && \
    echo "torchvision==${TORCHVISION_VERSION}" >> requirements.in && \
    echo "torchaudio==${TORCHAUDIO_VERSION}" >> requirements.in && \
    echo "pillow>=12.1.1" >> requirements.in && \
    TORCH_INDEX_URL="https://download.pytorch.org/whl/${TORCH_INDEX_SUFFIX}" && \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_EXTRA_INDEX_URL="${TORCH_INDEX_URL}" \
    pip-compile --generate-hashes --output-file=requirements.lock --strip-extras --allow-unsafe requirements.in && \
    python3.12 -m pip install --no-cache-dir --ignore-installed --require-hashes \
    --index-url https://pypi.org/simple \
    --extra-index-url "${TORCH_INDEX_URL}" \
    -r requirements.lock && \
    TORCH_VERSION="${TORCH_VERSION}" TORCHVISION_VERSION="${TORCHVISION_VERSION}" TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION}" \
    python3.12 -c 'import importlib.metadata as m, os, sys; expected = {"torch": os.environ["TORCH_VERSION"], "torchvision": os.environ["TORCHVISION_VERSION"], "torchaudio": os.environ["TORCHAUDIO_VERSION"]}; mismatches = [f"{pkg}: expected {version}, got {m.version(pkg)}" for pkg, version in expected.items() if m.version(pkg) != version]; sys.exit("\n".join(mismatches) if mismatches else 0)'

# Pre-populate ComfyUI-Manager cache so first cold start skips the slow registry fetch
COPY scripts/prebake-manager-cache.py /tmp/prebake-manager-cache.py
RUN python3.12 /tmp/prebake-manager-cache.py /tmp/build/ComfyUI/user/__manager/cache

# Bake ComfyUI + custom nodes into a known location for runtime copy
RUN printf '%s\n' \
    "COMFYUI_VERSION=${COMFYUI_VERSION}" \
    "MANAGER_SHA=${MANAGER_SHA}" \
    "KJNODES_SHA=${KJNODES_SHA}" \
    "CIVICOMFY_SHA=${CIVICOMFY_SHA}" \
    "RUNPODDIRECT_SHA=${RUNPODDIRECT_SHA}" \
    > /tmp/build/ComfyUI/.runpod-bundle-version && \
    cp -r /tmp/build/ComfyUI /opt/comfyui-baked

# ============================================================================
# Stage 2: Runtime - Clean image with pre-installed packages
# ============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg
ENV FILEBROWSER_CONFIG=/workspace/runpod-slim/.filebrowser.json

# ---- CUDA variant (re-declared for runtime stage) ----
ARG CUDA_VERSION_DASH=12-8
ARG TORCH_VERSION
ARG TORCHVISION_VERSION
ARG TORCHAUDIO_VERSION

# ---- FileBrowser version pin (set in docker-bake.hcl) ----
ARG FILEBROWSER_VERSION
ARG FILEBROWSER_SHA256

# Keep runtime pip installs aligned with the baked CUDA-specific PyTorch stack.
RUN printf "torch==%s\ntorchvision==%s\ntorchaudio==%s\n" \
    "$TORCH_VERSION" "$TORCHVISION_VERSION" "$TORCHAUDIO_VERSION" \
    > /opt/comfyui-runtime-constraints.txt

# Update and install runtime dependencies, CUDA, and common tools
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    git \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    build-essential \
    libssl-dev \
    wget \
    gnupg \
    xz-utils \
    openssh-client \
    openssh-server \
    nano \
    curl \
    htop \
    tmux \
    ca-certificates \
    less \
    net-tools \
    iputils-ping \
    procps \
    openssl \
    ffmpeg \
    rsync \
    && wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb \
    && dpkg -i cuda-keyring_1.1-1_all.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends cuda-minimal-build-${CUDA_VERSION_DASH} \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm cuda-keyring_1.1-1_all.deb \
    && rm -f /usr/lib/python3.12/EXTERNALLY-MANAGED

# Copy Python packages, executables, and Jupyter data from builder stage
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/local/share/jupyter /usr/local/share/jupyter

# Register Jupyter extensions (pip --ignore-installed skips post-install hooks)
RUN mkdir -p /usr/local/etc/jupyter/jupyter_server_config.d && \
    echo '{"ServerApp":{"jpserver_extensions":{"jupyter_server_terminals":true,"jupyterlab":true,"jupyter_resource_usage":true,"jupyterlab_nvdashboard":true}}}' \
    > /usr/local/etc/jupyter/jupyter_server_config.d/extensions.json

# Copy baked ComfyUI + custom nodes from builder stage
COPY --from=builder /opt/comfyui-baked /opt/comfyui-baked

# Remove uv to force ComfyUI-Manager to use pip (uv doesn't respect --system-site-packages properly)
RUN pip uninstall -y uv 2>/dev/null || true && \
    rm -f /usr/local/bin/uv /usr/local/bin/uvx

# Install FileBrowser (pinned version with checksum)
RUN curl -fSL "https://github.com/filebrowser/filebrowser/releases/download/${FILEBROWSER_VERSION}/linux-amd64-filebrowser.tar.gz" -o /tmp/fb.tar.gz && \
    echo "${FILEBROWSER_SHA256}  /tmp/fb.tar.gz" | sha256sum -c - && \
    tar xzf /tmp/fb.tar.gz -C /usr/local/bin filebrowser && \
    rm /tmp/fb.tar.gz

# Set CUDA environment variables
ENV PATH=/usr/local/cuda/bin:${PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64

# Allow container to start on hosts with older CUDA 12.x drivers
ENV NVIDIA_REQUIRE_CUDA=""
ENV NVIDIA_DISABLE_REQUIRE=true
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Jupyter is included in the lock file and installed in the builder stage

# Configure SSH for root login
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    mkdir -p /run/sshd && \
    rm -f /etc/ssh/ssh_host_*

# Create workspace directory
RUN mkdir -p /workspace/runpod-slim
WORKDIR /workspace/runpod-slim

# Expose ports
EXPOSE 8188 22 8888 8080

# Copy start script
COPY scripts/start.sh /start.sh

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    update-alternatives --set python3 /usr/bin/python3.12

ENTRYPOINT ["/start.sh"]
