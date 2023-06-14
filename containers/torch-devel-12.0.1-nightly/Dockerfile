ARG BASE_IMAGE=nvcr.io/nvidia/cuda:12.0.1-cudnn8-devel-ubuntu22.04

FROM ${BASE_IMAGE} as dev-base

WORKDIR /

RUN mkdir /workspace

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends\
    git\
    wget\
    curl\
    bash\
    libgl1\
    software-properties-common\
    openssh-server && \ 
add-apt-repository ppa:deadsnakes/ppa && \
apt install python3.10-dev python3.10-venv -y --no-install-recommends && \
        ln -s /usr/bin/python3.10 /usr/bin/python && \
        rm /usr/bin/python3 && \
        ln -s /usr/bin/python3.10 /usr/bin/python3 && \
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \ 
python get-pip.py && \
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu121 && \ 
pip install -U jupyterlab ipywidgets jupyter-archive jupyter_contrib_nbextensions && \
jupyter nbextension enable --py widgetsnbextension && \
apt-get clean && pip cache purge  && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

ADD start.sh /
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
