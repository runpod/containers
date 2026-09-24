# Curated default image for Runpod Sandboxes. Deliberately ships no nginx,
# sshd or Jupyter: commands are executed from outside the container, and the
# image has to pass gVisor suitability validation to be marked isSandbox.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ARG, not ENV — an interactive `apt` in the sandbox should behave normally.
ARG DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# 26.04's system Python is externally managed; without this every `pip install`
# in a sandbox fails.
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    build-essential ca-certificates curl git jq less openssh-client \
    python-is-python3 python3 python3-dev python3-pip python3-venv ripgrep \
    sudo tini tmux unzip wget xz-utils zip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Node from the official tarball rather than apt: Ubuntu's `npm` pulls in a
# vendored node-* tree (babel, handlebars, pacote) old enough to fail the
# HIGH/CRITICAL gate. 24 is the current LTS and the first line whose bundled
# npm carries a patched pacote.
ARG NODE_VERSION=24.21.0
ARG NODE_SHA256=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/node.tar.xz \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" && \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
        --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md && \
    rm /tmp/node.tar.xz && \
    node --version && npm --version

# Pinned rather than :latest — a warm pool is keyed on the image, so an
# upstream rebuild would silently split the pool.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /usr/local/bin/

# Ubuntu images since 24.04 ship a stock `ubuntu` account on uid 1000; drop it
# so the sandbox user owns the conventional uid.
RUN if id ubuntu &>/dev/null; then userdel --remove ubuntu; fi && \
    useradd --create-home --shell /bin/bash --uid 1000 user && \
    echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user && \
    chmod 0440 /etc/sudoers.d/user

USER user
WORKDIR /home/user

# Commands are exec'd into a long-lived sandbox, and whatever they orphan gets
# reparented to pid 1. `sleep` never reaps, so tini runs as pid 1 instead and
# forwards signals to the whole group on teardown.
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["sleep", "infinity"]
