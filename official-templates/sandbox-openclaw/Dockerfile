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
    build-essential jq less python3-pip ripgrep tmux unzip wget zip zstd sudo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Chromium's shared libraries, but not Chromium: a baked browser goes stale and
# cannot be patched, while `playwright install chromium` downloads a current one
# and then fails to start without these. They are what `--with-deps` would fetch
# through apt, which a sandbox has no root for.
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
    libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libnspr4 \
    libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxkbcommon0 libxrandr2 && \
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

# Without this the gateway refuses to serve and the container reports
# unhealthy forever, since a sandbox is never claimed with credentials in
# hand. `--allow-unconfigured` would also start it, but upstream marks that
# flag dev-only and it repairs nothing.
RUN openclaw config set gateway.mode local

# ENTRYPOINT, HEALTHCHECK and WORKDIR are left exactly as upstream: pid 1 is
# still their tini, and both the command below and the healthcheck resolve
# relative to /app, so moving WORKDIR would break them.
#
# CMD only adds --bind: inside a container the gateway defaults to 0.0.0.0 and
# then refuses to start unauthenticated, which a sandbox can never satisfy at
# boot. Bound to loopback it serves the exec'd `openclaw` CLI straight away;
# exposing the Control UI means setting a token first, which is the user's
# call once they have one.
CMD ["node", "openclaw.mjs", "gateway", "--bind", "loopback"]
