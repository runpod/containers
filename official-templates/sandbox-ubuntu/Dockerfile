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
    build-essential ca-certificates curl git jq less nodejs npm openssh-client \
    python-is-python3 python3 python3-dev python3-pip python3-venv ripgrep \
    sudo tini unzip wget zip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

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
