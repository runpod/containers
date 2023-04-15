ARG BASE_IMAGE=runpod/pytorch:3.10-2.0.0-117
FROM ${BASE_IMAGE} as dev-base

WORKDIR /src

RUN pip install torch transformers accelerate

RUN git clone --recurse-submodules https://github.com/nomic-ai/gpt4all.git
RUN cd gpt4all && git submodule update --init

RUN mkdir -p /opt/gpt4all
RUN cp gpt4all/chat/gpt4all-* /opt/gpt4all/

# If gpt4all-lora-quantized.bin exists in chat dir, comment out below
RUN apt update \
    && apt install -y wget \
    && cd /opt/gpt4all \
    && wget https://the-eye.eu/public/AI/models/nomic-ai/gpt4all/gpt4all-lora-quantized.bin


# Update Python to 3.11
RUN apt remove python3-apt -y
RUN apt autoremove -y
RUN apt autoclean -y
RUN apt install python3-apt -y
RUN apt-get install software-properties-common build-essential -y
RUN apt install wget build-essential libncursesw5-dev libssl-dev \
    libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev zlib1g-dev -y
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt install python3.11-dev python3.11-venv -y
RUN pip install virtualenv

# Python Client
RUN git clone https://github.com/nomic-ai/nomic.git
RUN cd nomic && pip install .[GPT4All]
RUN pip install nomic
RUN cd nomic/bin && pip wheel peft-0.3.0.dev0-py3-none-any.whl && \
    pip install transformers-4.28.0.dev0-py3-none-any.whl

RUN echo '#!/bin/bash' > /usr/local/bin/gpt4all \
    && echo 'cd /opt/gpt4all' >> /usr/local/bin/gpt4all \
    && echo './gpt4all-lora-quantized-linux-x86 -m ./gpt4all-lora-quantized.bin' >> /usr/local/bin/gpt4all \
    && chmod +x /usr/local/bin/gpt4all


# GUI
RUN git clone https://github.com/nomic-ai/gpt4all-ui
RUN cd gpt4all-ui && bash ./install.sh
RUN rm /src/gpt4all-ui/models/gpt4all-lora-quantized-ggml.bin
RUN wget https://huggingface.co/ParisNeo/GPT4All/resolve/main/gpt4all-lora-quantized-ggml.bin -O /src/gpt4all-ui/models/gpt4all-lora-quantized-ggml.bin
# RUN cp /opt/gpt4all/gpt4all-lora-quantized.bin /src/gpt4all-ui/models/gpt4all-lora-quantized.bin


ADD start.sh /src
RUN chmod +x /src/start.sh
CMD [ "/src/start.sh" ]
