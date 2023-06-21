# syntax=docker/dockerfile:1
FROM pytorch/pytorch:1.13.1-cuda11.6-cudnn8-devel

ARG VERSION=5.0.0
ARG DEBIAN_FRONTEND=noninteractive

LABEL bittensor.image.authors="bittensor.com"                                           \
    bittensor.image.vendor="Bittensor"                                                  \
    bittensor.image.title="bittensor/bittensor"                                         \
    bittensor.image.description="Bittensor: Incentivized Peer to Peer Neural Networks"  \
    bittensor.image.source="https://github.com/opentensor/bittensor.git"                \
    bittensor.image.revision="${VCS_REF}"                                               \
    bittensor.image.created="${BUILD_DATE}"                                             \
    bittensor.image.documentation="https://app.gitbook.com/@opentensor/s/bittensor/"    \
    bittensor.dependencies.versions.torch="1.13.1"                                      \
    bittensor.dependencies.versions.cuda="11.6"

ENV PM2_HOME="/root/.pm2"

#nvidia key migration
RUN apt-key del 7fa2af80
RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/3bf863cc.pub
RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu2004/x86_64/7fa2af80.pub

# Update and upgrade the base image, install dependencies, remove unnecessary packages
RUN apt update && apt upgrade -y && \
    apt install -y rsync curl sudo nano git htop netcat wget unzip python3-dev python3-pip tmux apt-utils cmake build-essential nginx && \
    apt autoremove -y && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

## Upgrade pip
RUN pip3 install --upgrade --no-cache-dir pip

# Install nvm and pm2
RUN curl -o install_nvm.sh https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.1/install.sh && \
    echo 'fabc489b39a5e9c999c7cab4d281cdbbcbad10ec2f8b9a7f7144ad701b6bfdc7 install_nvm.sh' | sha256sum --check && \
    bash install_nvm.sh && \
    rm install_nvm.sh

# Use node 16 and install pm2
RUN bash -c "source $HOME/.nvm/nvm.sh && \
    nvm install 16 && \
    npm install --location=global pm2"

# Clone bittensor and install
WORKDIR /root/.bittensor/
RUN git clone https://github.com/opentensor/bittensor.git . && \
    git checkout v$VERSION && \
    python3 -m pip install --no-cache-dir . && \
    python3 -m pip install --no-cache-dir https://github.com/opentensor/cubit/releases/download/v1.1.2/cubit-1.1.2-cp310-cp310-linux_x86_64.whl

# Move necessary directories
RUN mkdir -p /runpod_bittensor_tmp && \
    mv /root/.bittensor /runpod_bittensor_tmp/ && \
    mv /root/.npm /runpod_bittensor_tmp/ && \
    mv /root/.nvm /runpod_bittensor_tmp/


WORKDIR /root


COPY .bashrc /.bashrc
COPY welcome.txt /welcome.txt

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY --from=scripts start.sh /
RUN chmod +x /start.sh && chmod +x /pre_start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
