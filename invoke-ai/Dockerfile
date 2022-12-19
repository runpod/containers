FROM ghcr.io/ebr/invokeai:development

WORKDIR /invokeai

ENV HUGGINGFACE_TOKEN=$HF_TOKEN
ENV INVOKEAI_ROOT=/workspace

RUN ./scripts/configure_invokeai.py --yes

RUN unset HUGGINGFACE_TOKEN

RUN apt update && apt install -y \
    git openssh-server &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

WORKDIR /workspace

ADD start.sh /start.sh
RUN chmod a+x /start.sh
SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
