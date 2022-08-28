FROM continuumio/miniconda3

# Set bash as default shell, non-interactive
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash

# Create workspace working directory
RUN mkdir /weights && mkdir -p /root/.cache/huggingface && mkdir -p /workspace/out
WORKDIR /workspace

# Build with some basic utilities
RUN apt-get update && apt-get install -y \
    openssh-server &&\
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

ADD huggingface /root/.cache/huggingface
COPY stable-diffusion /workspace/stable-diffusion
RUN ls stable-diffusion
WORKDIR /workspace/stable-diffusion
RUN conda env create -f environment.yaml

RUN mkdir -p /root/.cache/huggingface && mkdir -p /workspace/out
ADD ./sd.ckpt /weights/
ADD start.sh /start.sh
RUN chmod +x start.sh

CMD [ "/start.sh" ]