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
apt-transport-https ca-certificates && \
update-ca-certificates

WORKDIR /workspace

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git

WORKDIR /workspace/stable-diffusion-webui

RUN python -m venv /workspace/stable-diffusion-webui/venv
ENV PATH="/workspace/stable-diffusion-webui/venv/bin:$PATH"

RUN pip install -U jupyterlab ipywidgets jupyter-archive gdown
RUN jupyter nbextension enable --py widgetsnbextension

WORKDIR /workspace/stable-diffusion-webui

ADD install.py .
RUN python -m install --skip-torch-cuda-test
RUN pip install --upgrade --force-reinstall xformers==0.0.18 torch torchvision torchaudio

RUN apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    apt update

ADD relauncher.py .
ADD webui-user.sh .
ADD start.sh /start.sh
RUN chmod a+x /start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
