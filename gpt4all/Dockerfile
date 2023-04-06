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


# Python Client
RUN git clone https://github.com/nomic-ai/nomic.git
RUN cd nomic && pip install .[GPT4All]
RUN pip install nomic
RUN cd nomic/bin && pip wheel peft-0.3.0.dev0-py3-none-any.whl && \
    pip install transformers-4.28.0.dev0-py3-none-any.whl


CMD [ "/start.sh" ]
