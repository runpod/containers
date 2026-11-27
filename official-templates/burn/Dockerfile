ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Burn's Vulkan backend (wgpu) needs the NVIDIA container toolkit to inject the
# graphics driver (libEGL_nvidia, libGLX_nvidia) and its Vulkan ICD, which only
# happens with the `graphics` capability. CUDA images default to
# `compute,utility`, which the CUDA backend and nvidia-smi need. `video` and
# `display` are left out: nothing here uses them.
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics

# Rust toolchain, installed system-wide. Both homes live in /opt, not
# /workspace, so a network volume mounted over /workspace does not hide them.
ENV RUSTUP_HOME=/opt/rustup \
    CARGO_HOME=/opt/cargo \
    PATH=/opt/cargo/bin:${PATH}

# Docker ENV only reaches processes started from the container's environment.
# A login shell for another user (`su - <user>`, SSH as that user) starts from
# a clean one, so login shells get the same three variables here.
COPY --chmod=644 rust-env.sh /etc/profile.d/rust-env.sh

# rustup-init is pinned by version and checksum; the toolchain by version.
# Burn 0.22 needs Rust 1.95 or later.
# The checksum is for the x86_64 rustup-init, the only platform the bake file
# builds (linux/amd64). The arch check makes an arm64 build fail here with a
# clear message instead of at the checksum.
ARG TARGETARCH
ARG RUSTUP_VERSION=1.29.3
ARG RUSTUP_SHA256=b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55
ARG RUST_VERSION=1.100.0
RUN if [ "${TARGETARCH:-amd64}" != "amd64" ]; then \
        echo "Only linux/amd64 is supported (RUSTUP_SHA256 is for x86_64), got ${TARGETARCH}" >&2; \
        exit 1; \
    fi && \
    wget -q --https-only --secure-protocol=TLSv1_2 --max-redirect=3 -O /tmp/rustup-init \
        "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/x86_64-unknown-linux-gnu/rustup-init" && \
    echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum -c - && \
    chmod +x /tmp/rustup-init && \
    /tmp/rustup-init -y --no-modify-path --profile minimal \
        --default-toolchain "${RUST_VERSION}" \
        --component rustfmt,clippy,rust-analyzer,rust-src && \
    rm /tmp/rustup-init && \
    rustc --version && cargo --version

# The Vulkan loader (libvulkan1), which Burn's Vulkan backend needs at runtime,
# and vulkan-tools for checking the driver from a shell (`vulkaninfo --summary`).
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends libvulkan1 vulkan-tools && \
    rm -rf /var/lib/apt/lists/*

# The NVIDIA container toolkit mounts a Vulkan ICD that loads the driver through
# libGLX_nvidia, which needs an X server: on a headless pod the loader reports
# "Found no drivers!". This second ICD loads the same driver through
# libEGL_nvidia, which works without one. The loader reads both directories, so
# on a host where the GLX path does work the GPU may be listed twice.
COPY nvidia_egl_icd.json /usr/share/vulkan/icd.d/nvidia_egl_icd.json

# Cargo's registry and git checkouts, and the starter below, are shared through
# the `rust` group, so a non-root user added to it can build without
# downloading everything again.
#
# Membership in `rust` is trusted as much as root. A member can edit the
# extracted crate sources (every build.rs included), the registry index and
# cache, and the starter's target/, and root runs that code the next time it
# builds or runs anything with cargo. Only add users you would give root to.
# The toolchain and /opt/cargo/bin stay writable by root only, which keeps a
# member from replacing rustc or cargo themselves, but that is not a security
# boundary while the shared crates are writable.
#
# Every cargo build also locks and updates files in the root of CARGO_HOME
# (.package-cache, .package-cache-mutate, and the .global-cache SQLite database
# with its journal). Without write access to them cargo builds without the lock
# that keeps two users' builds apart, and every build warns "failed to save
# last-use data". So the group needs to write those files and create new ones
# next to them. CARGO_HOME is therefore group-writable with the sticky bit:
# a group member can add files but cannot rename or delete bin/ or anything
# else they do not own. The setgid bit gives the files they create the `rust`
# group, so the next user can open them too.
#
# Group permissions are fixed inside each RUN that creates the files. A chmod
# in a later RUN would copy every file it touches into a new layer.

# Rust kernel for the JupyterLab that runpod/base starts. `evcxr_jupyter
# --install` only writes root's per-user kernel directory, so the kernelspec is
# moved to the system one (/usr/local/share/jupyter/kernels), where every user
# sees it.
ARG EVCXR_VERSION=0.22.0
RUN --mount=type=cache,target=/root/.cache/evcxr-target,sharing=locked \
    groupadd --system rust && \
    chgrp rust "${CARGO_HOME}" && \
    chmod 3775 "${CARGO_HOME}" && \
    install -d -g rust -m 2775 "${CARGO_HOME}/registry" "${CARGO_HOME}/git" && \
    CARGO_TARGET_DIR=/root/.cache/evcxr-target \
        cargo install --locked "evcxr_jupyter@${EVCXR_VERSION}" && \
    evcxr_jupyter --install && \
    jupyter kernelspec install --name rust /root/.local/share/jupyter/kernels/rust && \
    rm -rf /root/.local/share/jupyter/kernels/rust && \
    rm -rf "${CARGO_HOME}/registry/src" && \
    chgrp -R rust "${CARGO_HOME}/registry" "${CARGO_HOME}/git" && \
    chmod -R g+rwX "${CARGO_HOME}/registry" "${CARGO_HOME}/git" && \
    find "${CARGO_HOME}/registry" "${CARGO_HOME}/git" -type d -exec chmod g+s {} +

# Starter project: a GPU check across Burn's CUDA and Vulkan backends. Building
# it here fills the cargo registry with Burn and its dependencies and leaves a
# compiled copy, so `cargo run --release` in it starts in seconds. Cargo.lock
# pins every transitive dependency, and --locked fails the build if it is stale.
# The permission fix only touches files that lack group write, i.e. the ones
# this RUN created, so nothing from the evcxr layer is copied up. Cargo's lock
# and cache files in the root of CARGO_HOME are fixed here, after the last
# cargo run, which rewrites them anyway.
COPY --chown=root:rust starter /opt/burn-starter
WORKDIR /opt/burn-starter
RUN cargo build --release --locked && \
    find "${CARGO_HOME}" -maxdepth 1 -type f \( -name '.package-cache*' -o -name '.global-cache*' \) \
        -exec chgrp rust {} + -exec chmod g+rw {} + && \
    find "${CARGO_HOME}/registry" "${CARGO_HOME}/git" /opt/burn-starter ! -group rust -exec chgrp rust {} + && \
    find "${CARGO_HOME}/registry" "${CARGO_HOME}/git" /opt/burn-starter ! -perm -g+w -exec chmod g+rwX {} + && \
    find "${CARGO_HOME}/registry" "${CARGO_HOME}/git" /opt/burn-starter -type d ! -perm -g+s -exec chmod g+s {} +

WORKDIR /

# Override the NVIDIA CUDA entrypoint, which blocks boot on hosts whose driver
# is older than the image's CUDA (e.g. driver 550 only supports CUDA 12.4).
ENTRYPOINT ["/start.sh"]
