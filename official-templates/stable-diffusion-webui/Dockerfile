FROM nvidia/cuda:11.8.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND noninteractive
ENV SHELL=/bin/bash
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu
ENV PATH="/workspace/venv/bin:$PATH"

WORKDIR /workspace

# Set up shell and update packages
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies
RUN rm -f /etc/apt/sources.list.d/*.list && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get update --yes && \
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends \
    git openssh-server libglib2.0-0 libsm6 libgl1 libxrender1 libxext6 ffmpeg wget curl psmisc rsync vim bc nginx \
    pkg-config libffi-dev libcairo2 libcairo2-dev libgoogle-perftools4 libtcmalloc-minimal4 apt-transport-https \
    software-properties-common ca-certificates && \
    update-ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python 3.10
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt install python3.10-dev python3.10-venv -y --no-install-recommends && \
    ln -s /usr/bin/python3.10 /usr/bin/python && \
    rm /usr/bin/python3 && \
    ln -s /usr/bin/python3.10 /usr/bin/python3 && \
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \python get-pip.py && \
    pip install -U --no-cache-dir pip

# Create a virtual environment
RUN python -m venv /workspace/venv && \
    pip install -U --no-cache-dir jupyterlab jupyterlab_widgets ipykernel ipywidgets

WORKDIR /

ARG WEBUI_VERSION

# Install Automatic1111's WebUI
RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git && \
    cd /stable-diffusion-webui && \
    git checkout tags/${WEBUI_VERSION} && \
    pip install httpx>=0.25.0 xformers && \
    pip install --no-cache-dir --no-deps -r requirements_versions.txt && \
    python -c "from launch import prepare_environment; prepare_environment()" --skip-torch-cuda-test

WORKDIR /stable-diffusion-webui

# Apply hotfix to replace `pytorch_lightning.utilities.distributed` with `pytorch_lightning.utilities.rank_zero`
# see https://github.com/AUTOMATIC1111/stable-diffusion-webui/issues/11458#issuecomment-1609900319
RUN sed -i 's/pytorch_lightning.utilities.distributed/pytorch_lightning.utilities.rank_zero/g' \
    repositories/stable-diffusion-stability-ai/ldm/models/diffusion/ddpm.py && \
    sed -i 's/pytorch_lightning.utilities.distributed/pytorch_lightning.utilities.rank_zero/g' \
    extensions-builtin/LDSR/sd_hijack_ddpm_v1.py

# Install DeForum
RUN git clone https://github.com/deforum-art/sd-webui-deforum extensions/deforum && \
    cd extensions/deforum && \
    pip install basicsr && \
    pip install -r requirements.txt

# Install ControlNet
RUN git clone https://github.com/Mikubill/sd-webui-controlnet.git extensions/sd-webui-controlnet && \
    cd extensions/sd-webui-controlnet && \
    pip install -r requirements.txt

WORKDIR / 

RUN mv /workspace/venv /venv && \
    mkdir -p /workspace/downloader && git clone https://github.com/jjangga0214/sd-models-downloader.git /workspace/downloader

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

WORKDIR /stable-diffusion-webui

COPY relauncher.py webui-user.sh ./

WORKDIR /workspace

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY --from=scripts start.sh /
RUN chmod +x /start.sh && chmod +x /pre_start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
