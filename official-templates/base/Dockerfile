ARG BASE_IMAGE
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

# Update, upgrade, install packages and clean up
RUN apt-get update --yes && \
    apt-get upgrade --yes && \

    # Basic Utilities
    apt install --yes --no-install-recommends \
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

    # Required for SSH access
    openssh-server \

    procps \
    rsync \
    sudo \
    software-properties-common \
    unzip \
    wget \
    zip && \

    # Build Tools and Development
    apt install --yes --no-install-recommends \
    build-essential \
    make \
    cmake \
    gfortran \
    libblas-dev \
    liblapack-dev && \

    # Image and Video Processing
    apt install --yes --no-install-recommends \
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
    libxvidcore-dev && \

    # Deep Learning Dependencies and Miscellaneous
    apt install --yes --no-install-recommends \
    libatlas-base-dev \
    libffi-dev \
    libhdf5-serial-dev \
    libsm6 \
    libssl-dev && \

    # File Systems and Storage
    apt install --yes --no-install-recommends \
    cifs-utils \
    nfs-common \
    zstd &&\

    # Add the Python PPA and install Python versions
    add-apt-repository ppa:deadsnakes/ppa && \
    apt install --yes --no-install-recommends \
    python3.7-dev \
    python3.7-venv \
    python3.7-distutils \
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
    python3.11-distutils && \

    # Cleanup
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \

    # Set locale
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install pip
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.7 get-pip.py && \
    python3.8 get-pip.py && \
    python3.9 get-pip.py && \
    python3.10 get-pip.py && \
    python3.11 get-pip.py

# Get the latest pip for all python versions
RUN python3.7 -m pip install --upgrade pip && \
    python3.8 -m pip install --upgrade pip && \
    python3.9 -m pip install --upgrade pip && \
    python3.10 -m pip install --upgrade pip && \
    python3.11 -m pip install --upgrade pip

# Install virtualenv
RUN python3.7 -m pip install virtualenv && \
    python3.8 -m pip install virtualenv && \
    python3.9 -m pip install virtualenv && \
    python3.10 -m pip install virtualenv && \
    python3.11 -m pip install virtualenv

# Install pip drop-in replacement uv (https://github.com/astral-sh/uv)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Extras
RUN /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
ENV PATH="/home/linuxbrew/.linuxbrew/bin:${PATH}"
RUN brew update && brew install pyenv
RUN brew tap filebrowser/tap && brew install filebrowser

# Temporary while bash path gets fixed https://github.com/astral-sh/uv/issues/1586
RUN brew install uv

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts start.sh /
COPY post_start.sh /
RUN chmod +x /start.sh && \
    chmod +x /post_start.sh

# Welcome Message
COPY --from=logo runpod.txt /etc/runpod.txt
RUN echo 'cat /etc/runpod.txt' >> /root/.bashrc
RUN echo 'echo -e "\nFor detailed documentation and guides, please visit:\n\033[1;34mhttps://docs.runpod.io/\033[0m and \033[1;34mhttps://blog.runpod.io/\033[0m\n\n"' >> /root/.bashrc

CMD ["/start.sh"]
