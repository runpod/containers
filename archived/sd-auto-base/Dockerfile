FROM runpod/pytorch:3.10-2.0.0-117 AS runtime

ENV DEBIAN_FRONTEND noninteractive

RUN apt update && \
apt install -y  --no-install-recommends \
software-properties-common \
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
libcairo2-dev \
libgoogle-perftools4 libtcmalloc-minimal4 \
apt-transport-https ca-certificates && \
update-ca-certificates

WORKDIR /workspace

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git

WORKDIR /workspace/stable-diffusion-webui

RUN python -m venv /workspace/venv
ENV PATH="/workspace/venv/bin:$PATH"

RUN pip install -U jupyterlab ipywidgets jupyter-archive gdown
RUN jupyter nbextension enable --py widgetsnbextension

WORKDIR /workspace/stable-diffusion-webui

ADD install.py .
RUN python -m install --skip-torch-cuda-test
RUN pip install xformers
