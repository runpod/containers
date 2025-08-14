ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV PYTHONUNBUFFERED=True
ENV DEBIAN_FRONTEND=noninteractive

# Set the default workspace directory
ENV RP_WORKSPACE=/workspace

# Override the default huggingface cache directory.
ENV HF_HOME="${RP_WORKSPACE}/.cache/huggingface/"

# Shared python package cache
ENV VIRTUALENV_OVERRIDE_APP_DATA="${RP_WORKSPACE}/.cache/virtualenv/"
ENV PIP_CACHE_DIR="${RP_WORKSPACE}/.cache/pip/"
ENV UV_CACHE_DIR="${RP_WORKSPACE}/.cache/uv/"

# Faster transfer of models from the hub to the container
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV HF_XET_HIGH_PERFORMANCE=1

# modern pip workarounds
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_ROOT_USER_ACTION=ignore

# Set TZ and Locale
ENV TZ=Etc/UTC

WORKDIR /

# Update and upgrade
RUN apt-get update --yes && \
    apt-get upgrade --yes

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install 
RUN apt-get install --yes --no-install-recommends \
    ca-certificates curl dirmngr file git gpg gpg-agent inotify-tools \
    jq lsof nano nginx openssh-server rsync software-properties-common \
    sudo tmux unzip vim wget zip build-essential make cmake gfortran ffmpeg \
    libatlas-base-dev libavcodec-dev libavfilter-dev libavformat-dev libblas-dev \
    libffi-dev libhdf5-dev libgl1 libjpeg-dev liblapack-dev libpng-dev \
    libpostproc-dev libsm6 libssl-dev libswscale-dev libtiff-dev \
    libv4l-dev libx264-dev libxrender-dev libxvidcore-dev \
    cifs-utils nfs-common zstd

# Add the Python PPA
RUN add-apt-repository ppa:deadsnakes/ppa -y

# Install Python 
RUN apt-get install --yes --no-install-recommends \
    python3.9-dev python3.9-venv python3.9-distutils \
    python3.10-dev python3.10-venv python3.10-distutils \
    python3.11-dev python3.11-venv python3.11-distutils \
    python3.12-dev python3.12-venv \
    python3.13-dev python3.13-venv python-is-python3 && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install pip if we are not ROCm
RUN if [ -z "${ROCM_PATH}"]; then \
        curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
        python3.9  get-pip.py && \
        python3.10 get-pip.py && \
        python3.11 get-pip.py && \
        python3.12 get-pip.py && \
        python3.13 get-pip.py && \
        rm get-pip.py; \
    fi

# ensurepip (it's there, we just installed it^) and install virtualenv
RUN if [ -z "${ROCM_PATH}"]; then \
        python3.9 -m pip install --upgrade pip virtualenv && \
        python3.10 -m pip install --upgrade pip virtualenv && \
        python3.11 -m pip install --upgrade pip virtualenv && \
        python3.12 -m pip install --upgrade pip virtualenv && \
        python3.13 -m pip install --upgrade pip virtualenv; \
    fi

# Install Jupyter and related packages (always with Python 3.10)
RUN python3.10 -m pip install --upgrade --no-cache-dir \
    jupyterlab \
    ipywidgets \
    jupyter-archive \
    notebook==7.4.2

# Install pip drop-in replacement uv (https://github.com/astral-sh/uv)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> /etc/profile.d/uv.sh && \
    chmod +x /etc/profile.d/uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv --version

# Install filebrowser
RUN curl -LsSf https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy snippets /etc/nginx/snippets
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Remove existing SSH host keys
RUN rm -f /etc/ssh/ssh_host_*

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Script
COPY --from=scripts --chmod=755 start.sh /

# Welcome Message
COPY --from=logo runpod.txt /etc/runpod.txt
RUN echo 'cat /etc/runpod.txt' >> /root/.bashrc
RUN echo 'echo -e "\nFor detailed documentation and guides, please visit:\n\033[1;34mhttps://docs.runpod.io/\033[0m and \033[1;34mhttps://blog.runpod.io/\033[0m\n\n"' >> /root/.bashrc

CMD ["/start.sh"]
