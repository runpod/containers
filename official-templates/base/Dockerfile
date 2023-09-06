FROM nvidia/cuda:11.1.1-cudnn8-runtime-ubuntu20.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV DEBIAN_FRONTEND=noninteractive
ENV HF_DATASETS_CACHE=/runpod_volume/.cache/huggingface/datasets

WORKDIR /

# Update, upgrade, install packages and clean up
RUN apt-get update --yes && \
    apt-get upgrade --yes && \

    # Basic Utilities
    apt install --yes --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    libgl1 \
    nano \
    nginx \
    openssh-server \
    software-properties-common \
    unzip \
    wget \
    zip && \

    # Build Tools and Development
    apt install --yes --no-install-recommends \
    build-essential \
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
    libavresample-dev \
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
    nfs-common && \

    # Add the Python PPA and install Python versions
    add-apt-repository ppa:deadsnakes/ppa && \
    apt install --yes --no-install-recommends \
    python3.8-dev \
    python3.8-venv \
    python3.9-dev \
    python3.9-venv \
    python3.10-dev \
    python3.10-venv \
    python3.11-dev \
    python3.11-venv && \

    # Cleanup
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \

    # Set locale
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install pip
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.8 get-pip.py && \
    python3.9 get-pip.py && \
    python3.10 get-pip.py && \
    python3.11 get-pip.py

# Get the latest pip for all python versions
RUN python3.8 -m pip install --upgrade pip && \
    python3.9 -m pip install --upgrade pip && \
    python3.10 -m pip install --upgrade pip && \
    python3.11 -m pip install --upgrade pip


# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts start.sh /
RUN chmod +x /start.sh

CMD ["/start.sh"]
