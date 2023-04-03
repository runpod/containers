# start from runpod pytorch container
ARG BASE_IMAGE=runpod/pytorch:3.10-1.13.1-116

FROM ${BASE_IMAGE} as dev-base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND noninteractive\

SHELL=/bin/bash

RUN apt-key del 7fa2af80
RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/3bf863cc.pub
RUN apt-get update --yes && \
    # - apt-get upgrade is run to patch known vulnerabilities in apt-get packages as
    #   the ubuntu base image is rebuilt too seldom sometimes (less than once a month)
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends\
    wget\
    bash\
    openssh-server &&\
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
RUN /usr/bin/python3 -m pip install --upgrade pip
RUN pip install jupyterlab
RUN pip install ipywidgets

#RUN mkdir /workspace && 
RUN cd /workspace && git clone https://github.com/oobabooga/text-generation-webui.git && cd /workspace/text-generation-webui && pip install -r requirements.txt
RUN cd /workspace/text-generation-webui && python download-model.py PygmalionAI/pygmalion-6b
#RUN cd /workspace/text-generation-webui && python download-model.py EleutherAI/gpt-j-6B

ADD start_chatbot_server.sh /workspace/text-generation-webui/
ADD start_textgen_server.sh /workspace/text-generation-webui/

RUN chmod +x /workspace/text-generation-webui/start_chatbot_server.sh
RUN chmod +x /workspace/text-generation-webui/start_textgen_server.sh

ADD start.sh /
RUN chmod +x /start.sh

CMD [ "/start.sh" ]