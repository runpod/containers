ARG BASE_IMAGE=nvidia/cuda:11.6.2-devel-ubuntu20.04

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
    bash\
    libgl1\
    software-properties-common\
    openssh-server && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt install python3.10-dev -y --no-install-recommends && \
	ln -s /usr/bin/python3.10 /usr/bin/python && \
	rm /usr/bin/python3 && \
	ln -s /usr/bin/python3.10 /usr/bin/python3 && \
	curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
	python get-pip.py && apt-get autoclean
RUN pip install -U --no-cache-dir pip && pip install -U --no-cache-dir torch==1.13.1+cu116 torchvision==0.14.1+cu116 torchaudio==0.13.1 --extra-index-url https://download.pytorch.org/whl/cu116 && pip install -U --no-cache-dir jupyterlab jupyterlab_widgets ipywidgets jupyter-archive

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

ADD start.sh /
RUN chmod +x /start.sh

CMD [ "/start.sh" ]

