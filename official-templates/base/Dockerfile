ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV PYTHONUNBUFFERED=True
ENV DEBIAN_FRONTEND=noninteractive

# Set the base release version
ARG BASE_RELEASE_VERSION
ENV BASE_RELEASE_VERSION=${BASE_RELEASE_VERSION}

# Override the default huggingface cache directory.
ENV HF_HOME="/runpod-volume/.cache/huggingface/"
ENV HF_DATASETS_CACHE="/runpod-volume/.cache/huggingface/datasets/"
ENV DEFAULT_HF_METRICS_CACHE="/runpod-volume/.cache/huggingface/metrics/"
ENV DEFAULT_HF_MODULES_CACHE="/runpod-volume/.cache/huggingface/modules/"
ENV HUGGINGFACE_HUB_CACHE="/runpod-volume/.cache/huggingface/hub/"
ENV HUGGINGFACE_ASSETS_CACHE="/runpod-volume/.cache/huggingface/assets/"

# Faster transfer of models from the hub to the container
ENV HF_HUB_ENABLE_HF_TRANSFER="1"

# Shared python package cache
ENV VIRTUALENV_OVERRIDE_APP_DATA="/runpod-volume/.cache/virtualenv/"
ENV PIP_CACHE_DIR="/runpod-volume/.cache/pip/"
ENV UV_CACHE_DIR="/runpod-volume/.cache/uv/"

# Set Default Python Version
ENV PYTHON_VERSION="3.10"

WORKDIR /

# Update and upgrade
RUN apt-get update --yes && \
    apt-get upgrade --yes

# Install basic utilities
RUN apt install --yes --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    file \
    git \
    inotify-tools \
    jq \
    libgl1 \
    lsof \
    vim \
    nano \
    tmux \
    nginx \
    openssh-server \
    procps \
    rsync \
    sudo \
    software-properties-common \
    unzip \
    wget \
    zip

# Install build tools and development packages
RUN apt install --yes --no-install-recommends \
    build-essential \
    make \
    cmake \
    gfortran \
    libblas-dev \
    liblapack-dev

# Install image and video processing libraries
RUN apt install --yes --no-install-recommends \
    ffmpeg \
    libavcodec-dev \
    libavfilter-dev \
    libavformat-dev \
    libavutil-dev \
    libjpeg-dev \
    libpng-dev \
    libpostproc-dev \
    libswresample-dev \
    libswscale-dev \
    libtiff-dev \
    libv4l-dev \
    libx264-dev \
    libxext6 \
    libxrender-dev \
    libxvidcore-dev

# Install deep learning dependencies and miscellaneous
RUN apt install --yes --no-install-recommends \
    libatlas-base-dev \
    libffi-dev \
    libhdf5-serial-dev \
    libsm6 \
    libssl-dev

# Install file systems and storage
RUN apt install --yes --no-install-recommends \
    cifs-utils \
    nfs-common \
    zstd

# Add the Python PPA
RUN add-apt-repository ppa:deadsnakes/ppa

# Install Python 3.8-3.11 with distutils
RUN apt install --yes --no-install-recommends \
    python3.8-dev \
    python3.8-venv \
    python3.8-distutils \
    python3.9-dev \
    python3.9-venv \
    python3.9-distutils \
    python3.10-dev \
    python3.10-venv \
    python3.10-distutils \
    python3.11-dev \
    python3.11-venv \
    python3.11-distutils

# Install Python 3.12-3.13 (distutils is included in dev package for newer versions)
RUN apt install --yes --no-install-recommends \
    python3.12-dev \
    python3.12-venv \
    python3.13-dev \
    python3.13-venv

# Cleanup
RUN apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set locale
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install pip
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.8 get-pip.py && \
    python3.9 get-pip.py && \
    python3.10 get-pip.py && \
    python3.11 get-pip.py && \
    python3.12 get-pip.py && \
    python3.13 get-pip.py && \
    rm get-pip.py

# Get the latest pip for all python versions
RUN python3.8 -m pip install --upgrade pip && \
    python3.9 -m pip install --upgrade pip && \
    python3.10 -m pip install --upgrade pip && \
    python3.11 -m pip install --upgrade pip && \
    python3.12 -m pip install --upgrade pip && \
    python3.13 -m pip install --upgrade pip

# Install virtualenv
RUN python3.8 -m pip install virtualenv && \
    python3.9 -m pip install virtualenv && \
    python3.10 -m pip install virtualenv && \
    python3.11 -m pip install virtualenv && \
    python3.12 -m pip install virtualenv && \
    python3.13 -m pip install virtualenv

# Install Jupyter and related packages (always with Python 3.10)
RUN python3.10 -m pip install --upgrade --no-cache-dir \
    jupyterlab \
    ipywidgets \
    jupyter-archive \
    jupyter_contrib_nbextensions \
    notebook==6.5.5 && \
    jupyter contrib nbextension install --user && \
    jupyter nbextension enable --py widgetsnbextension

# Install pip drop-in replacement uv (https://github.com/astral-sh/uv)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> /etc/profile.d/uv.sh && \
    chmod +x /etc/profile.d/uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv --version

# Install additional tools that were previously installed via Homebrew
# Install pyenv via git
RUN git clone https://github.com/pyenv/pyenv.git /opt/pyenv && \
    echo 'export PYENV_ROOT="/opt/pyenv"' >> /etc/profile.d/pyenv.sh && \
    echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> /etc/profile.d/pyenv.sh && \
    echo 'if command -v pyenv 1>/dev/null 2>&1; then eval "$(pyenv init -)"; fi' >> /etc/profile.d/pyenv.sh && \
    chmod +x /etc/profile.d/pyenv.sh

# Install filebrowser
RUN curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts --chmod=755 start.sh /
COPY --chmod=755 post_start.sh /

# Welcome Message
COPY --from=logo runpod.txt /etc/runpod.txt
RUN echo 'cat /etc/runpod.txt' >> /root/.bashrc
RUN echo 'echo -e "\nFor detailed documentation and guides, please visit:\n\033[1;34mhttps://docs.runpod.io/\033[0m and \033[1;34mhttps://blog.runpod.io/\033[0m\n\n"' >> /root/.bashrc

CMD ["/start.sh"]
