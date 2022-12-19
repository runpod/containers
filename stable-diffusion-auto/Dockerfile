FROM runpod/stable-diffusion-models:1.5 as build

FROM debian:buster AS runtime

# Build with some basic utilities
RUN apt update && apt install -y \
    git python3 python3-venv openssh-server libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg wget curl &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

WORKDIR /workspace

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git
WORKDIR /workspace/stable-diffusion-webui
RUN git pull

COPY --from=build /models/v1-5-pruned-emaonly.ckpt /workspace/stable-diffusion-webui/models/Stable-diffusion/v1-5-pruned-emaonly.ckpt
COPY --from=build /root/.cache/huggingface /root/.cache/huggingface

ADD webui-user.sh /workspace/stable-diffusion-webui/webui-user.sh

RUN ./webui.sh -f 1 

SHELL ["/bin/bash", "-c"]
ENV PATH="${PATH}:/workspace/venv"

RUN mkdir -p /root/.cache/huggingface
RUN mkdir -p /workspace/outputs

ADD start.sh /start.sh
RUN chmod a+x /start.sh
SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
