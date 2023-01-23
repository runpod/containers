FROM runpod/stable-diffusion-models:1.5 as build

WORKDIR /
RUN rm -rf /stable-diffusion
RUN mkdir stable-diffusion
ADD environment.yml /stable-diffusion/environment.yaml
WORKDIR /stable-diffusion
RUN conda update -n base -c defaults conda
RUN conda env create -f environment.yaml
SHELL ["conda", "run", "-n", "ldm", "/bin/bash", "-c"]

RUN conda install -c conda-forge conda-pack
RUN conda-pack --ignore-missing-files -n ldm -o /tmp/env.tar --ignore-editable-packages && \
    mkdir -p /home/kasm-user/Desktop/venv && cd /home/kasm-user/Desktop/venv && tar xf /tmp/env.tar && \
    rm /tmp/env.tar

RUN /home/kasm-user/Desktop/venv/bin/conda-unpack

FROM runpod/stable-diffusion:base-v2.1 as models-2.1

FROM kasmweb/ubuntu-focal-desktop:1.12.0
USER root
COPY --chown=kasm-user:kasm-user --from=build /home/kasm-user/Desktop/venv /home/kasm-user/Desktop/venv

# Build with some basic utilities
RUN apt update && apt install -y \
    fonts-noto-color-emoji sudo git openssh-server libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg wget curl &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo 'kasm-user ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

RUN sed -i.bak 's/-sslOnly//' /dockerstartup/vnc_startup.sh
RUN sed -i '/^\s*pem_key:/a \ \ \ \ require_ssl: false' /etc/kasmvnc/kasmvnc.yaml
USER kasm-user

ENV VIRTUAL_ENV=/home/kasm-user/Desktop/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /home/kasm-user/Desktop

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git
WORKDIR /home/kasm-user/Desktop/stable-diffusion-webui
RUN git pull
RUN git checkout 3e22e294135ed0327ce9d9738655ff03c53df3c0
RUN pip install -r requirements.txt

RUN mkdir repositories; \
git clone https://github.com/CompVis/stable-diffusion.git repositories/stable-diffusion && \
git clone https://github.com/CompVis/taming-transformers.git repositories/taming-transformers && \
git clone https://github.com/sczhou/CodeFormer.git repositories/CodeFormer && \
git clone https://github.com/salesforce/BLIP.git repositories/BLIP && \
git clone https://github.com/crowsonkb/k-diffusion.git repositories/k-diffusion && \
git clone https://github.com/Stability-AI/stablediffusion.git  repositories/stable-diffusion-stability-ai && \
cd extensions && \
git clone https://github.com/yfszzx/stable-diffusion-webui-images-browser.git && \
cd stable-diffusion-webui-images-browser && git fetch && cd .. && \
git clone https://github.com/d8ahazard/sd_dreambooth_extension.git && \
cd sd_dreambooth_extension && git fetch && git checkout c5cb58328c555ac27679422b1da940a9b19de6f2 && \
pip install -r requirements.txt && cd ..

COPY --chown=kasm-user:kasm-user --from=build /models/v1-5-pruned-emaonly.ckpt /home/kasm-user/Desktop/stable-diffusion-webui/models/Stable-diffusion/v1-5-pruned-emaonly.ckpt
COPY --chown=kasm-user:kasm-user --from=build /root/.cache/huggingface /root/.cache/huggingface
COPY --chown=kasm-user:kasm-user --from=models-2.1 /models/v2-1_768-ema-pruned.ckpt /home/kasm-user/Desktop/stable-diffusion-webui/models/Stable-diffusion/v2-1_768-ema-pruned.ckpt
COPY --chown=kasm-user:kasm-user --from=models-2.1 /models/v2-1_768-ema-pruned.yaml /home/kasm-user/Desktop/stable-diffusion-webui/models/Stable-diffusion/v2-1_768-ema-pruned.yaml

RUN sudo rm /home/kasm-user/Desktop/venv/bin/ffmpeg

ADD StableDiffusion.desktop /home/kasm-user/Desktop/StableDiffusion.desktop

RUN sudo chmod a+x /home/kasm-user/Desktop/StableDiffusion.desktop
