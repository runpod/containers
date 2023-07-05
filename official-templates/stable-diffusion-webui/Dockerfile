FROM nvidia/cuda:11.8.0-devel-ubuntu22.04

ARG WEBUI_VERSION=v1.3.2
ARG DREAMBOOTH_VERSION=1.0.14

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu
ENV PATH="/workspace/venv/bin:$PATH"
ENV TORCH_COMMAND="pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu117"
WORKDIR /workspace

COPY --from=scripts cache-sd-model.py .
COPY --from=scripts install-automatic.py .

RUN wget https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned.ckpt -O /sd-models/v1-5-pruned.ckpt
RUN wget https://huggingface.co/lllyasviel/ControlNet-v1-1/resolve/main/control_v11p_sd15_canny.pth -O /cn-models/control_v11p_sd15_canny.pth

COPY requirements_dreambooth.txt /requirements_dreambooth.txt

COPY requirements.txt /requirements.txt
COPY requirements_versions.txt /requirements_versions.txt

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
    nginx \
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
    pip install -U --no-cache-dir jupyterlab jupyterlab_widgets ipykernel ipywidgets && \
    git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git && \
    cd stable-diffusion-webui && \
    git checkout tags/v1.3.2 && \
    mv /workspace/install-automatic.py /workspace/stable-diffusion-webui/ && \
    mv /requirements.txt ./requirements.txt && \
    mv /requirements_versions.txt ./requirements_versions.txt && \
    python -m install-automatic --skip-torch-cuda-test && \
    cd /workspace/stable-diffusion-webui && \
    git clone https://github.com/deforum-art/sd-webui-deforum extensions/deforum && \
    cd extensions/deforum && \
    pip install -r requirements.txt && \
    cd /workspace/stable-diffusion-webui && \
    git clone https://github.com/Mikubill/sd-webui-controlnet.git extensions/sd-webui-controlnet && \
    cd extensions/sd-webui-controlnet && \
    pip install -r requirements.txt && \
    #cd /workspace/stable-diffusion-webui && \
    #git clone https://github.com/d8ahazard/sd_dreambooth_extension.git extensions/sd_dreambooth_extension && \
    #cd extensions/sd_dreambooth_extension && \
    #git checkout dev && \
    #  git reset ${DREAMBOOTH_VERSION} --hard && \
    #  mv /requirements_dreambooth.txt ./requirements.txt && pip install -r requirements.txt && \
    cd /workspace/stable-diffusion-webui/ && \
    mv /workspace/cache-sd-model.py /workspace/stable-diffusion-webui/ && \
    python cache-sd-model.py --use-cpu=all --ckpt /sd-models/SDv1-5.ckpt && \
    pip cache purge && \
    apt clean && \
    mv /workspace/venv /venv && \
    mv /workspace/stable-diffusion-webui /stable-diffusion-webui

COPY pre_start.sh /pre_start.sh
COPY relauncher.py webui-user.sh /stable-diffusion-webui/

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY --from=scripts start.sh /
RUN chmod +x /start.sh && chmod +x /pre_start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
