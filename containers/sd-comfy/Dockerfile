FROM nvidia/cuda:11.7.1-cudnn8-devel-ubuntu22.04 AS runtime

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu

RUN apt update --yes && \
apt upgrade --yes && \
apt install --yes --no-install-recommends \
git \
openssh-server \
libglib2.0-0 \
libsm6 \
libgl1 \
libxrender1 \
libxext6 \
ffmpeg \
wget \
curl \
psmisc \
rsync \
vim \
pkg-config \
libffi-dev \
libcairo2 \
libcairo2-dev \
libgoogle-perftools4 \
libtcmalloc-minimal4 \
apt-transport-https \
software-properties-common \
ca-certificates && \
update-ca-certificates && \
add-apt-repository ppa:deadsnakes/ppa && \
apt install python3.10-dev python3.10-venv -y --no-install-recommends && \
ln -s /usr/bin/python3.10 /usr/bin/python && \
rm /usr/bin/python3 && \
ln -s /usr/bin/python3.10 /usr/bin/python3 && \
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \python get-pip.py && \
pip install -U --no-cache-dir pip && \
python -m venv /workspace/venv && \
export PATH="/workspace/venv/bin:$PATH" && \
pip install -U --no-cache-dir jupyterlab jupyterlab_widgets ipywidgets jupyter-archive && \
git clone https://github.com/comfyanonymous/ComfyUI.git && \
cd /ComfyUI && \
pip install --no-cache-dir -r requirements.txt && \
pip install --no-cache-dir triton && \
pip cache purge

WORKDIR /ComfyUI

