ARG BASE_IMAGE=mambaorg/micromamba

FROM ${BASE_IMAGE} as dev-base
USER root

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash
RUN apt-get update --yes && \
    # - apt-get upgrade is run to patch known vulnerabilities in apt-get packages as
    #   the ubuntu base image is rebuilt too seldom sometimes (less than once a month)
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends\
    bash \
    openssh-server &&\
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
RUN micromamba install --yes --name base --channel conda-forge \
    python=3.9.1 \
    jupyterlab \
    nano \
    wget \
    ipywidgets && \ 
micromamba clean --all --yes

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]

