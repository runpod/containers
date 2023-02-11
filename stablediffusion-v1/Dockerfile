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
    mkdir /workspace/venv && cd /workspace/venv && tar xf /tmp/env.tar && \
    rm /tmp/env.tar

RUN /workspace/venv/bin/conda-unpack

FROM debian:buster-slim AS runtime

COPY --from=build /workspace/venv /workspace/venv
COPY --from=build /models/v1-5-pruned-emaonly.ckpt /workspace/v1-5-pruned-emaonly.ckpt
COPY --from=build /root/.cache/huggingface /root/.cache/huggingface

RUN mkdir -p /root/.cache/huggingface && mkdir -p /workspace/outputs &&  rm /workspace/venv/bin/ffmpeg

SHELL ["/bin/bash", "-c"]
ENV PATH="${PATH}:/workspace/venv/bin"

# Build with some basic utilities
RUN apt update && apt install -y \
    git openssh-server libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg wget curl &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

WORKDIR /workspace

RUN cd /workspace && \
rm -rf stable-diffusion-webui && \
git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git && \
cd /workspace/stable-diffusion-webui && \
git pull
WORKDIR /workspace/stable-diffusion-webui

RUN mkdir repositories; \
git clone https://github.com/CompVis/stable-diffusion.git repositories/stable-diffusion && \
git clone https://github.com/CompVis/taming-transformers.git repositories/taming-transformers && \
git clone https://github.com/sczhou/CodeFormer.git repositories/CodeFormer && \
git clone https://github.com/salesforce/BLIP.git repositories/BLIP && \
git clone https://github.com/crowsonkb/k-diffusion.git repositories/k-diffusion && \
git clone https://github.com/Stability-AI/stablediffusion.git  repositories/stable-diffusion-stability-ai && \
cd extensions && \
git clone https://github.com/yfszzx/stable-diffusion-webui-images-browser.git && \
cd stable-diffusion-webui-images-browser && git fetch && cd ..

ADD relauncher.py .
ADD webui-user.sh .
ADD start.sh /start.sh
RUN chmod a+x /start.sh && \
chmod +x webui.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
