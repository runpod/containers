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

# Install. apt-get upgrade also pulls the patched ca-certificates
# (CON-1869: drops emSign root, CVE-2026-111943).
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends \
    build-essential ca-certificates curl git jq less openssh-client \
    python-is-python3 python3 python3-dev python3-pip python3-venv ripgrep \
    sudo tini tmux unzip wget xz-utils zip zstd && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Canonical's service manager, dropped into the base image outside dpkg, so
# there is no package to purge. tini is pid 1 and nothing invokes it, but its
# Go stdlib carries 13 findings (2 CRITICAL) with no fixed build in 26.04.
RUN rm -rf /usr/bin/pebble /var/lib/pebble

# 26.04 builds tar against openat2 with no fallback, and gVisor does not
# implement that call (google/gvisor#14451), so `tar -x` fails in a sandbox.
# The 24.04 build is the same 1.35 and works. Drop once the runtime catches up.
ARG TAR_DEB=tar_1.35+dfsg-3ubuntu0.4_amd64.deb
ARG TAR_DEB_SHA256=fdf41a87936824e50c8ac11b0b22d1395aeb0754feef2dae5575b5d5a93793ec
RUN curl -fsSL --proto '=https' --tlsv1.2 -o "/tmp/${TAR_DEB}" \
        "https://archive.ubuntu.com/ubuntu/pool/main/t/tar/${TAR_DEB}" && \
    echo "${TAR_DEB_SHA256}  /tmp/${TAR_DEB}" | sha256sum -c - && \
    dpkg -i "/tmp/${TAR_DEB}" && \
    apt-mark hold tar && \
    rm "/tmp/${TAR_DEB}"

# Node from the official tarball rather than apt: Ubuntu's `npm` pulls in a
# vendored node-* tree (babel, handlebars, pacote) old enough to fail the
# HIGH/CRITICAL gate. 24 is the current LTS and the first line whose bundled
# npm carries a patched pacote.
#
# npm is then replaced with a pinned release: the npm bundled with Node 24
# (11.19.x) vendors brace-expansion, ip-address, undici, tar and
# postcss-selector-parser with HIGH advisories, and no Node build fixes that.
# Keep this pin when NODE_VERSION is bumped, unless that Node already bundles
# this npm or newer. Stay on npm 11: 12 blocks git/remote deps and dependency
# lifecycle scripts by default, which breaks what agents do in a sandbox.
ARG NODE_VERSION=24.22.3
ARG NODE_SHA256=4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb
ARG NPM_VERSION=11.21.2
ARG NPM_SHA256=8ad8563b81e71b90ef405b140bccf3ba9b5e7884ab210bd49ee4e2f4bc6f61f5
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/node.tar.xz \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" && \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
        --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md && \
    rm /tmp/node.tar.xz && \
    curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/npm.tgz \
        "https://registry.npmjs.org/npm/-/npm-${NPM_VERSION}.tgz" && \
    echo "${NPM_SHA256}  /tmp/npm.tgz" | sha256sum -c - && \
    npm install --global --no-fund --no-audit /tmp/npm.tgz && \
    npm cache clean --force && \
    rm /tmp/npm.tgz && \
    node --version && \
    test "$(npm --version)" = "${NPM_VERSION}"

# Pinned by digest, not just by tag — a warm pool is keyed on the image, so an
# upstream rebuild or a re-pushed tag would silently split the pool.
COPY --from=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /uvx /usr/local/bin/

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
