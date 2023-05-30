# Base image
ARG BASE_IMAGE=nvcr.io/nvidia/cuda:12.0.1-cudnn8-devel-ubuntu22.04
FROM ${BASE_IMAGE} as dev-base

# Working directory
WORKDIR /workspace

# Set necessary environment variables
ENV DEBIAN_FRONTEND=noninteractive\
    SHELL=/bin/bash\
    PATH="/root/.local/bin:$PATH"

# Update, upgrade, and install necessary packages
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends\
    git\
    wget\
    curl\
    libgl1\
    software-properties-common\
    openssh-server\
    python3.10-dev python3.10-venv && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Set Python and pip
RUN ln -s /usr/bin/python3.10 /usr/bin/python && \
    curl https://bootstrap.pypa.io/get-pip.py | python && \
    rm -f get-pip.py

# Install Python packages
COPY dist/xformers-0.0.21a205b24.d20230530-cp310-cp310-linux_x86_64.whl /tmp
RUN pip install --no-cache-dir --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu121 && \
    pip install --no-cache-dir -U jupyterlab ipywidgets jupyter-archive jupyter_contrib_nbextensions /tmp/xformers-0.0.21+a205b24.d20230530-cp310-cp310-linux_x86_64.whl && \
    jupyter nbextension enable --py widgetsnbextension && \
    rm -f /tmp/xformers-0.0.21a205b24.d20230530-cp310-cp310-linux_x86_64.whl

# Add start script
COPY start.sh /workspace
RUN chmod +x /workspace/start.sh

# Set default command
CMD [ "/workspace/start.sh" ]
