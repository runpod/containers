FROM ghcr.io/ebr/invokeai:latest-cuda as builder

FROM library/ubuntu:22.04 AS runtime

WORKDIR /workspace

COPY --from=builder /invokeai /invokeai
 
ARG DEBIAN_FRONTEND=noninteractive

ENV VIRTUAL_ENV=/invokeai/.venv
ENV PATH=${VIRTUAL_ENV}/bin:$PATH
ENV HUGGINGFACE_TOKEN=$HF_TOKEN
ENV INVOKEAI_ROOT=/workspace
ENV PYTHONUNBUFFERED=1
ENV PATH="$VIRTUAL_ENV/bin:$PATH" 


RUN apt update && apt install -y --no-install-recommends \
    git \ 
    openssh-server \
    ncdu \
    iotop \
    bzip2 \
    libglib2.0-0 \
    libgl1-mesa-glx \
    python3-venv \
    python3-pip \
    build-essential \
    python3-opencv \
    libopencv-dev &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    apt autoclean

RUN python -m venv $VIRTUAL_ENV

WORKDIR /invokeai

RUN ./scripts/configure_invokeai.py --yes

RUN unset HUGGINGFACE_TOKEN

WORKDIR /workspace

RUN pip install jupyterlab && \
pip install ipywidgets && \
jupyter nbextension enable --py widgetsnbextension

COPY --from=builder /usr/lib/x86_64-linux-gnu/pkgconfig /usr/lib/x86_64-linux-gnu/pkgconfig

# build patchmatch
RUN python -c "from patchmatch import patch_match"

## workaround for non-existent initfile when runtime directory is mounted; see #1613
RUN touch /root/.invokeai

WORKDIR /

ADD start.sh /start.sh
RUN chmod a+x /start.sh
USER root
CMD [ "/start.sh" ]
USER root
