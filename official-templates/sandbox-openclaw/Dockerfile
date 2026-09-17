# OpenClaw sandbox template. The upstream image already ships Node 24, the
# `openclaw` CLI on PATH, git, curl, an ssh client and tini on Debian
# bookworm, so this layer only adds what a Runpod sandbox needs on top.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

USER root

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    jq less python3-pip ripgrep unzip wget zip sudo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Upstream runs as `node` with no route to root, so nothing can be installed
# from inside a sandbox.
RUN echo "node ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/node && \
    chmod 0440 /etc/sudoers.d/node

# Debian 12 marks the system Python externally managed.
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

USER node

# ENTRYPOINT, CMD, HEALTHCHECK and WORKDIR are left exactly as upstream: the
# gateway starts at boot, pid 1 is still their tini, and both the command
# (`node openclaw.mjs gateway`) and the healthcheck resolve relative to /app,
# so moving WORKDIR would break them.
