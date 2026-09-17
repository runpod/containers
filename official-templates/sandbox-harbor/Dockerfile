# Harbor sandbox template: a sandbox to drive agent evaluations from. Harbor
# tasks carry their own environment images, so this image is the harness side
# of a run, not the environment a trial executes in.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

USER root

# openssh-server carries sshd and sftp-server, which Harbor's Agent Sandbox
# Protocol speaks; no daemon is started here. tmux keeps a long eval run alive
# across a dropped connection.
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    openssh-server tmux && \
    rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Installed as a root-owned tool on PATH rather than into the user's home, so
# a sandbox cannot leave itself without a working `harbor`.
ARG HARBOR_VERSION=0.23.0
ENV UV_TOOL_DIR=/opt/uv-tools
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install --no-cache "harbor==${HARBOR_VERSION}" && \
    harbor --version

USER user
WORKDIR /home/user
