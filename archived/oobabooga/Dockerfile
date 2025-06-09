# start from runpod pytorch container
ARG BASE_IMAGE=runpod/pytorch:3.10-1.13.1-116

FROM ${BASE_IMAGE} AS dev-base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV SHELL=/bin/bash

RUN apt-key del 7fa2af80
RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/3bf863cc.pub
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends\
    wget\
    bash\
    rsync \
    openssh-server &&\
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
RUN /usr/bin/python3 -m pip install --upgrade pip
RUN pip install jupyterlab
RUN pip install ipywidgets

RUN cd /workspace && git clone https://github.com/oobabooga/text-generation-webui.git && cd /workspace/text-generation-webui && pip install -r requirements.txt
RUN cd /workspace/text-generation-webui && python download-model.py PygmalionAI/pygmalion-6b

RUN mv /workspace/text-generation-webui /text-generation-webui

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY post_start.sh /post_start.sh
COPY --chmod=755 --from=scripts start.sh /

CMD [ "/start.sh" ]
