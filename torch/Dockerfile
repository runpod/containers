ARG BASE_IMAGE=nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04

FROM ${BASE_IMAGE} as dev-base

WORKDIR /

RUN mkdir /workspace

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash
RUN apt-get update --yes && \
    # - apt-get upgrade is run to patch known vulnerabilities in apt-get packages as
    #   the ubuntu base image is rebuilt too seldom sometimes (less than once a month)
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends\
    git\
    wget\
    curl\
    git\
    bash\
    python3.9-distutils\ 
    software-properties-common\
    openssh-server
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt install python3.9 -y --no-install-recommends && \
	ln -s /usr/bin/python3.9 /usr/bin/python && \
	rm /usr/bin/python3 && \
	ln -s /usr/bin/python3.9 /usr/bin/python3
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
RUN python get-pip.py
RUN pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu116
RUN pip install -U jupyterlab ipywidgets jupyter-archive
RUN jupyter nbextension enable --py widgetsnbextension

RUN apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]

