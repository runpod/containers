# Harbor sandbox template: a sandbox to drive agent evaluations from. Harbor
# tasks carry their own environment images, so this image is the harness side
# of a run, not the environment a trial executes in. Hence no sshd: the Agent
# Sandbox Protocol runs over ssh towards the machine a trial executes on, and
# this is the end that dials out. Everything else comes from sandbox-ubuntu.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

# Installed as a root-owned tool on PATH rather than into the user's home, so
# a sandbox cannot leave itself without a working `harbor`.
ARG HARBOR_VERSION=0.23.0
ENV UV_TOOL_DIR=/opt/uv-tools
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install --no-cache "harbor==${HARBOR_VERSION}" && \
    harbor --version

USER user
WORKDIR /home/user
