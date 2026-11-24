# ============================================================================
# Stage 1: Builder - Download pinned sources and install all Python packages
# ============================================================================
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# ---- Version pins (set in docker-bake.hcl) ----
ARG COMFYUI_VERSION
ARG MANAGER_VERSION
ARG KJNODES_SHA
ARG CIVICOMFY_SHA
ARG RUNPODDIRECT_SHA
ARG TORCH_VERSION
ARG TORCHVISION_VERSION
ARG TORCHAUDIO_VERSION

# ---- CUDA variant (set in docker-bake.hcl per target) ----
ARG CUDA_VERSION_DASH=12-8
ARG TORCH_INDEX_SUFFIX=cu128
# torchaudio has no cu132 build; see docker-bake.hcl for why 13.2 uses +cpu.
ARG TORCHAUDIO_INDEX_SUFFIX=cu128
# Prebuilt SageAttention wheel for this exact torch + CUDA; empty skips it.
ARG SAGEATTENTION_VERSION=""
ARG SAGEATTENTION_WHEEL_URL=""
ARG SAGEATTENTION_SHA256=""

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
    && curl -fSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb -o cuda-keyring_1.1-1_all.deb \
    && dpkg -i cuda-keyring_1.1-1_all.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends cuda-minimal-build-${CUDA_VERSION_DASH} libcusparse-dev-${CUDA_VERSION_DASH} \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm cuda-keyring_1.1-1_all.deb \
    && rm -f /usr/lib/python3.12/EXTERNALLY-MANAGED

# Install pip and pip-tools for lock file generation.
RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.12 get-pip.py "pip==26.2.1" && \
    python3.12 -m pip install --no-cache-dir "pip-tools==7.6.2" && \
    rm get-pip.py

# Set CUDA environment for building
ENV PATH=/usr/local/cuda/bin:${PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64

# Download pinned source archives
WORKDIR /tmp/build
RUN curl -fSL "https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/${COMFYUI_VERSION}.tar.gz" -o comfyui.tar.gz && \
    mkdir -p ComfyUI && tar xzf comfyui.tar.gz --strip-components=1 -C ComfyUI && rm comfyui.tar.gz

# ComfyUI ships ComfyUI-Manager as a pip package it pins itself, and `main.py
# --enable-manager` loads that package. MANAGER_VERSION only mirrors the pin so
# the shipped Manager is visible in docker-bake.hcl and in the bundle manifest;
# a ComfyUI bump that moves the pin fails here instead of changing Manager
# silently.
RUN test "$(tr -d '[:space:]' < ComfyUI/manager_requirements.txt)" = "comfyui_manager==${MANAGER_VERSION}"

# Custom nodes: real git clones reset to the pinned commit. Real shared history
# with origin lets ComfyUI-Manager's git update path fast-forward instead of
# failing on the synthetic single-commit history these used to carry.
WORKDIR /tmp/build/ComfyUI/custom_nodes
RUN git clone "https://github.com/kijai/ComfyUI-KJNodes.git" ComfyUI-KJNodes && \
    git -C ComfyUI-KJNodes reset --hard "${KJNODES_SHA}" && \
    git clone "https://github.com/MoonGoblinDev/Civicomfy.git" Civicomfy && \
    git -C Civicomfy reset --hard "${CIVICOMFY_SHA}" && \
    git clone "https://github.com/MadiatorLabs/ComfyUI-RunpodDirect.git" ComfyUI-RunpodDirect && \
    git -C ComfyUI-RunpodDirect reset --hard "${RUNPODDIRECT_SHA}"

# Runpod fixes to the pinned sources: one patch per issue in patches/, paths
# relative to the ComfyUI root. git apply refuses a patch whose context has
# moved, so a pin bump that touches patched code fails the build instead of
# shipping without the fix: rebase the patch onto the new pin, or delete it
# once upstream has the fix. A node's patch is committed in its own clone:
# an uncommitted change there would block ComfyUI-Manager's `git pull`.
COPY patches/ /tmp/patches/
RUN git -C /tmp/build/ComfyUI apply --verbose /tmp/patches/*.patch && \
    for repo in /tmp/build/ComfyUI/custom_nodes/*/; do \
        git -C "$repo" diff --quiet || \
        git -C "$repo" -c user.name=- -c user.email=- commit -qam "Runpod patches"; \
    done

# ComfyUI core: synthetic git so Manager can read its version, patches already
# in the tagged commit. custom_nodes is excluded now that each node is its own
# clone. Core is image-managed (start.sh upgrades it), not via Manager.
WORKDIR /tmp/build/ComfyUI
RUN git init && git add -A -- . ':!custom_nodes' && \
    git -c user.name=- -c user.email=- commit -q -m "ComfyUI ${COMFYUI_VERSION}" && \
    git tag "${COMFYUI_VERSION}" && \
    git remote add origin https://github.com/comfyanonymous/ComfyUI.git

# Generate lock file from all requirements (including torch pins), then install with hash verification
WORKDIR /tmp/build
RUN cat ComfyUI/requirements.txt ComfyUI/manager_requirements.txt > requirements.in && \
    for node_dir in ComfyUI/custom_nodes/*/; do \
        if [ -f "$node_dir/requirements.txt" ]; then \
            cat "$node_dir/requirements.txt" >> requirements.in; \
        fi; \
    done && \
    echo "GitPython" >> requirements.in && \
    echo "opencv-python>=5.1.0.95" >> requirements.in && \
    echo "opencv-python-headless>=5.1.0.95" >> requirements.in && \
    echo "jupyter" >> requirements.in && \
    echo "jupyter-resource-usage" >> requirements.in && \
    echo "jupyterlab-nvdashboard" >> requirements.in && \
    sed -i -E '/^[[:space:]]*(torch|torchvision|torchaudio)([[:space:]]|[\[<>=!~;#]|$)/d' requirements.in && \
    echo "torch==${TORCH_VERSION}" >> requirements.in && \
    echo "torchvision==${TORCHVISION_VERSION}" >> requirements.in && \
    echo "torchaudio==${TORCHAUDIO_VERSION}" >> requirements.in && \
    echo "pillow>=13.0.0" >> requirements.in && \
    echo "tornado>=6.5.10" >> requirements.in && \
    echo "certifi>=2026.10.19" >> requirements.in && \
    echo "av>=19.0.0" >> requirements.in && \
    TORCH_INDEX_URL="https://download.pytorch.org/whl/${TORCH_INDEX_SUFFIX}" && \
    AUDIO_INDEX_URL="https://download.pytorch.org/whl/${TORCHAUDIO_INDEX_SUFFIX}" && \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_EXTRA_INDEX_URL="${TORCH_INDEX_URL} ${AUDIO_INDEX_URL}" \
    pip-compile --generate-hashes --output-file=requirements.lock --strip-extras --allow-unsafe requirements.in && \
    python3.12 -m pip install --no-cache-dir --ignore-installed --require-hashes \
    --index-url https://pypi.org/simple \
    --extra-index-url "${TORCH_INDEX_URL}" \
    --extra-index-url "${AUDIO_INDEX_URL}" \
    -r requirements.lock && \
    TORCH_VERSION="${TORCH_VERSION}" TORCHVISION_VERSION="${TORCHVISION_VERSION}" TORCHAUDIO_VERSION="${TORCHAUDIO_VERSION}" \
    python3.12 -c 'import importlib.metadata as m, os, sys; expected = {"torch": os.environ["TORCH_VERSION"], "torchvision": os.environ["TORCHVISION_VERSION"], "torchaudio": os.environ["TORCHAUDIO_VERSION"]}; mismatches = [f"{pkg}: expected {version}, got {m.version(pkg)}" for pkg, version in expected.items() if m.version(pkg) != version]; sys.exit("\n".join(mismatches) if mismatches else 0)'

# Manager's get_pip_cmd() probes `python -m pip --version` with a 5s timeout and
# treats a timeout as "pip is missing" — on a slow network volume a working pip
# reads as absent, and Manager then falls back to uv, which this image removes.
# The count assertion fails the build if the upstream pattern moves. find_spec
# locates the package without importing it: comfyui_manager/__init__.py pulls in
# comfy.cli_args, which is not importable outside a ComfyUI checkout.
RUN MANAGER_UTIL="$(python3.12 -c 'import importlib.util, os; print(os.path.join(os.path.dirname(importlib.util.find_spec("comfyui_manager").origin), "common", "manager_util.py"))')" && \
    test "$(grep -c 'timeout=5)' "$MANAGER_UTIL")" = 2 && \
    sed -i 's/timeout=5)/timeout=30)/g' "$MANAGER_UTIL" && \
    python3.12 -m compileall -q "$MANAGER_UTIL"

# ComfyUI listens on loopback behind the password proxy, and Manager loosens
# its install gates on a loopback --listen. start.sh pins the config values
# that close the gates in this Manager (see pin_manager_security). Newer
# Manager releases add allow_flagged_nodepack_install, ORed with loopback, so
# no config value closes it: fail here so a Manager bump decides about it.
RUN MANAGER_PKG="$(python3.12 -c 'import importlib.util, os; print(os.path.dirname(importlib.util.find_spec("comfyui_manager").origin))')" && \
    if grep -rq 'allow_flagged_nodepack_install' "$MANAGER_PKG" --include='*.py'; then \
        echo "ComfyUI-Manager gained allow_flagged_nodepack_install; review pin_manager_security in start.sh" >&2; exit 1; \
    fi

# Runpod fixes to Manager itself. Manager is a pip package, not part of the
# ComfyUI tree, so its patches live apart from patches/ and are applied to the
# installed package: the 403s on update_comfyui and comfyui_switch_version keep
# the image's pinned ComfyUI version, the ones on share and on the four routes
# that read a stored credential (openart, matrix, youml, comfyworkflows) keep
# Manager from handing those back over HTTP, and the '@' check refuses a node
# spec that would resolve to a target the caller did not name.
# Every one lands twice. __init__.py imports either glob/ or legacy/ depending
# on --enable-manager-legacy-ui, which this template documents, and the two
# carry the same routes; patching only glob/ would leave the legacy UI open.
# git apply refuses a patch whose context has moved, so a MANAGER_VERSION bump
# that touches this code fails the build instead of shipping without the fixes.
COPY manager-patches/ /tmp/manager-patches/
RUN MANAGER_PKG="$(python3.12 -c 'import importlib.util, os; print(os.path.dirname(importlib.util.find_spec("comfyui_manager").origin))')" && \
    git -C "$MANAGER_PKG" apply --verbose -p1 /tmp/manager-patches/*.patch && \
    python3.12 -m compileall -q "$MANAGER_PKG"

# SageAttention needs a compile per torch + CUDA pair, so it comes as a pinned
# wheel rather than through the lock. --no-deps keeps it from touching the
# hash-locked torch; the wheel's own torch==<exact> pin is checked instead.
# Not imported here: _qattn_sm90 links libcuda.so.1, which only a GPU host has.
RUN if [ -n "${SAGEATTENTION_WHEEL_URL}" ]; then \
        mkdir -p /tmp/sageattention && \
        wheel="/tmp/sageattention/sageattention-${SAGEATTENTION_VERSION}-cp312-cp312-linux_x86_64.whl" && \
        curl -fSL "${SAGEATTENTION_WHEEL_URL}" -o "${wheel}" && \
        printf '%s  %s\n' "${SAGEATTENTION_SHA256}" "${wheel}" > /tmp/sageattention/wheel.sha256 && \
        sha256sum -c /tmp/sageattention/wheel.sha256 && \
        python3.12 -m pip install --no-cache-dir --no-deps --no-index --find-links /tmp/sageattention \
            "sageattention==${SAGEATTENTION_VERSION}" && \
        rm -rf /tmp/sageattention && \
        TORCH_VERSION="${TORCH_VERSION}" python3.12 -c 'import importlib.metadata as m, os, sys; pin = "torch==" + os.environ["TORCH_VERSION"]; requires = m.requires("sageattention") or []; sys.exit(0 if pin in requires else f"sageattention requires {requires}, image has {pin}")'; \
    else \
        echo "No SageAttention wheel for this CUDA variant; skipping."; \
    fi

# Pre-populate ComfyUI-Manager cache so first cold start skips the slow registry fetch
COPY scripts/prebake-manager-cache.py /tmp/prebake-manager-cache.py
RUN python3.12 /tmp/prebake-manager-cache.py /tmp/build/ComfyUI/user/__manager/cache "${COMFYUI_VERSION}"

# Bake ComfyUI + custom nodes into a known location for runtime copy. The
# patch hashes are part of the manifest so start.sh re-syncs existing volumes
# when a patch is added or changed.
RUN printf '%s\n' \
    "COMFYUI_VERSION=${COMFYUI_VERSION}" \
    "MANAGER_VERSION=${MANAGER_VERSION}" \
    "KJNODES_SHA=${KJNODES_SHA}" \
    "CIVICOMFY_SHA=${CIVICOMFY_SHA}" \
    "RUNPODDIRECT_SHA=${RUNPODDIRECT_SHA}" \
    "$(sha256sum /tmp/patches/*.patch)" \
    > /tmp/build/ComfyUI/.runpod-bundle-version && \
    cp -r /tmp/build/ComfyUI /opt/comfyui-baked

# ============================================================================
# FileBrowser - built from source
# ============================================================================
# Upstream archived FileBrowser on 2026-09-01: FILEBROWSER_VERSION is its last
# release and no security fixes will follow. Its release binary carries the Go
# toolchain and modules of July 2026, so it is rebuilt here with a current Go
# and the vulnerable modules raised. Drop these stages when FileBrowser is
# replaced.
FROM golang:1.26.11-bookworm AS filebrowser-src

ARG FILEBROWSER_VERSION
ARG FILEBROWSER_COMMIT

# A git checkout, not the source tarball: Go stamps the module version from it
# (v2.63.23+dirty once go.mod is raised), so scanners still match FileBrowser's
# own advisories. A tarball build reports (devel) and they never match.
RUN git clone --quiet --depth 1 --branch "${FILEBROWSER_VERSION}" \
        https://github.com/filebrowser/filebrowser.git /src && \
    test "$(git -C /src rev-parse HEAD)" = "${FILEBROWSER_COMMIT}"
WORKDIR /src

# The web UI, embedded into the binary from frontend/dist (frontend/assets.go).
# Corepack runs the exact pnpm the project pins in package.json.
FROM node:24-bookworm-slim AS filebrowser-frontend

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
COPY --from=filebrowser-src /src /src
WORKDIR /src/frontend
RUN corepack enable && \
    pnpm install --frozen-lockfile && \
    pnpm run build

FROM filebrowser-src AS filebrowser-build

# pipefail: the stamp check below pipes `go version -m` into awk, and a
# failing go must fail the build, not hand awk empty input.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG FILEBROWSER_VERSION

# GOTOOLCHAIN=local: build with this image's Go, never a downloaded one.
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
COPY --from=filebrowser-frontend /src/frontend/dist /src/frontend/dist
RUN go get \
        github.com/andybalholm/brotli@v1.3.0 \
        github.com/klauspost/compress@v1.20.4 \
        golang.org/x/crypto@v0.59.0 \
        golang.org/x/image@v0.48.0 \
        golang.org/x/net@v0.62.0 \
        golang.org/x/sys@v0.50.0 \
        golang.org/x/text@v0.44.0 && \
    go mod tidy && \
    go build -trimpath \
        -ldflags "-s -w -X github.com/filebrowser/filebrowser/v2/version.Version=${FILEBROWSER_VERSION#v}" \
        -o /out/filebrowser . && \
    /out/filebrowser version && \
    fb_mod="$(go version -m /out/filebrowser | awk '$1 == "mod" { print $2, $3 }')" && \
    echo "FileBrowser module stamp: ${fb_mod}" && \
    case "${fb_mod}" in \
        "github.com/filebrowser/filebrowser/v2 ${FILEBROWSER_VERSION}" | \
        "github.com/filebrowser/filebrowser/v2 ${FILEBROWSER_VERSION}+dirty") ;; \
        *) echo "FileBrowser's module version is not ${FILEBROWSER_VERSION}: scanners would not match its advisories" >&2; exit 1 ;; \
    esac

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
ARG TORCH_INDEX_SUFFIX=cu128
ARG TORCH_VERSION
ARG TORCHVISION_VERSION
ARG TORCHAUDIO_VERSION

# Which venv on the network volume this image owns — one per torch CUDA build,
# since packages users install there (xformers, triton, sageattention,
# onnxruntime-gpu, nunchaku) are compiled against it. 13.0 used to share
# .venv-cu128; start.sh treats that as a move and reinstalls node deps.
ENV COMFYUI_VENV_NAME=.venv-${TORCH_INDEX_SUFFIX}

# Install NVIDIA's CUDA forward-compatibility driver libs (cuda-compat-*) so
# the image can run on hosts whose driver is older than the image's CUDA.
# start.sh only activates them after a cuInit() probe succeeds.
ARG INSTALL_CUDA_COMPAT=false

# ---- FileBrowser version pin (set in docker-bake.hcl) ----
ARG FILEBROWSER_VERSION
ARG FILEBROWSER_SHA256

# Keep runtime pip installs aligned with the baked CUDA-specific PyTorch stack.
# The pins carry a local version (+cu128), which PyPI does not serve — without
# this index every runtime install that touches torch fails to resolve.
ENV PIP_EXTRA_INDEX_URL="https://download.pytorch.org/whl/${TORCH_INDEX_SUFFIX}"
# pip's pinned here, so its "new release available" notice is noise — and users
# reading Manager install logs take it for an error.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN printf "torch==%s\ntorchvision==%s\ntorchaudio==%s\n" \
    "$TORCH_VERSION" "$TORCHVISION_VERSION" "$TORCHAUDIO_VERSION" \
    > /opt/comfyui-runtime-constraints.txt

# Install runtime deps, CUDA, and tools. apt-get upgrade also pulls the
# patched ca-certificates (CON-1869: drops emSign root, CVE-2026-111943).
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
    && curl -fSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb -o cuda-keyring_1.1-1_all.deb \
    && dpkg -i cuda-keyring_1.1-1_all.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends cuda-minimal-build-${CUDA_VERSION_DASH} \
    && if [ "${INSTALL_CUDA_COMPAT}" = "true" ]; then \
        apt-get install -y --no-install-recommends cuda-compat-${CUDA_VERSION_DASH} && \
        ln -sfn /usr/local/cuda/compat /opt/cuda-compat && \
        test -e /opt/cuda-compat/libcuda.so.1; \
    fi \
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

# FileBrowser, rebuilt from source in the stages above
COPY --from=filebrowser-build /out/filebrowser /usr/local/bin/filebrowser

# Set CUDA environment variables
ENV PATH=/usr/local/cuda/bin:${PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64

# Allow container to start on hosts with older CUDA 12.x drivers
ENV NVIDIA_REQUIRE_CUDA=""
ENV NVIDIA_DISABLE_REQUIRE=true
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Jupyter is included in the lock file and installed in the builder stage

# Key-only SSH: no root password is ever set. The greps fail the build if a
# future base image drops the stock lines and the edits land nowhere.
RUN sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    sed -i 's/^#*PermitUserEnvironment .*/PermitUserEnvironment yes/' /etc/ssh/sshd_config && \
    grep -q '^PasswordAuthentication no$' /etc/ssh/sshd_config && \
    grep -q '^PermitUserEnvironment yes$' /etc/ssh/sshd_config && \
    mkdir -p /run/sshd && \
    rm -f /etc/ssh/ssh_host_*

# Create workspace directory
RUN mkdir -p /workspace/runpod-slim
WORKDIR /workspace/runpod-slim

# Expose ports
EXPOSE 8188 22 8888 8080

# Copy start script
COPY scripts/start.sh /start.sh

# Password proxy in front of ComfyUI (see start.sh). It runs on the image's
# interpreter with ComfyUI's own aiohttp, so the build fails here if that
# stops importing rather than every pod failing at start.
COPY scripts/auth_proxy.py /opt/comfyui-auth-proxy/auth_proxy.py
RUN /usr/bin/python3.12 -I -c "import yarl; from aiohttp import web; web.AppKey" && \
    /usr/bin/python3.12 -I -m py_compile /opt/comfyui-auth-proxy/auth_proxy.py

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    update-alternatives --set python3 /usr/bin/python3.12

ENTRYPOINT ["/start.sh"]
