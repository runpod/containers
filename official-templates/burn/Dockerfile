ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Burn's Vulkan backend (wgpu) needs the NVIDIA container toolkit to inject the
# graphics driver and its Vulkan ICD, which only happens with the `graphics`
# capability. CUDA images default to `compute,utility`.
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Rust toolchain, installed system-wide. Both homes live in /opt, not
# /workspace, so a network volume mounted over /workspace does not hide them.
ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    PATH=/opt/cargo/bin:${PATH}

# rustup-init is pinned by version and checksum; the toolchain by version.
# Burn 0.22 needs Rust 1.95 or later.
ARG RUSTUP_VERSION=1.29.3
ARG RUSTUP_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
ARG RUST_VERSION=1.100.0
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/rustup-init \
        "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" && \
    echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c - && \
    chmod +x /tmp/rustup-init && \
    /tmp/rustup-init -y --no-modify-path --profile minimal \
        --default-toolchain "${RUST_VERSION}" \
        --component rustfmt,clippy,rust-analyzer,rust-src && \
    rm /tmp/rustup-init && \
    rustc --version && cargo --version

# Vulkan tools, for checking the driver from a shell (`vulkaninfo --summary`).
# The Vulkan loader itself already ships in the base image.
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends vulkan-tools && \
    rm -rf /var/lib/apt/lists/*

# The NVIDIA container toolkit mounts a Vulkan ICD that loads the driver through
# libGLX_nvidia, which needs an X server: on a headless pod the loader reports
# "Found no drivers!". This second ICD loads the same driver through
# libEGL_nvidia, which works without one. The loader reads both directories, so
# on a host where the GLX path does work the GPU may be listed twice.
COPY nvidia_egl_icd.json /usr/share/vulkan/icd.d/nvidia_egl_icd.json

# Rust kernel for the JupyterLab that runpod/base starts.
ARG EVCXR_VERSION=0.22.0
RUN --mount=type=cache,target=/root/.cache/evcxr-target,sharing=locked \
    CARGO_TARGET_DIR=/root/.cache/evcxr-target \
        cargo install --locked "evcxr_jupyter@${EVCXR_VERSION}" && \
    evcxr_jupyter --install && \
    rm -rf "${CARGO_HOME}/registry/src"

# Starter project: a GPU check across Burn's CUDA and Vulkan backends. Building
# it here fills the cargo registry with Burn and its dependencies and leaves a
# compiled copy, so `cargo run --release` in it starts in seconds.
ARG BURN_VERSION=0.22.1
COPY starter /opt/burn-starter
WORKDIR /opt/burn-starter
RUN sed -i "s/@BURN_VERSION@/${BURN_VERSION}/" Cargo.toml && \
    cargo build --release

# Let any user build in the toolchain and starter, not just root.
RUN chmod -R a+rwX "${RUSTUP_HOME}" "${CARGO_HOME}" /opt/burn-starter

WORKDIR /
