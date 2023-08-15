# devel needed for bitsandbytes requirement of libcudart.so, otherwise runtime sufficient
FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    software-properties-common \
    pandoc \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt install -y python3.10 python3-dev libpython3.10-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone the contents of your project into /app
WORKDIR /app
RUN git clone https://github.com/h2oai/h2ogpt.git

# Install Python packages
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10
RUN python3.10 -m pip install -r /app/h2ogpt/requirements.txt

# Now let's put our start.sh script into the container
WORKDIR /workspace
COPY start.sh /start.sh
RUN chmod +x /start.sh

ENTRYPOINT [ "/start.sh" ]
