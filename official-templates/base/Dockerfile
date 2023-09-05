FROM nvidia/cuda:12.2.0-runtime-ubuntu20.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV DEBIAN_FRONTEND=noninteractive
ENV HF_DATASETS_CACHE=/runpod_volume/.cache/huggingface/datasets

WORKDIR /

# Update, upgrade, install packages and clean up
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends git wget curl bash libgl1 software-properties-common openssh-server nginx && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt install "python3.8-dev" "python3.8-venv" -y --no-install-recommends && \
    apt install "python3.9-dev" "python3.9-venv" -y --no-install-recommends && \
    apt install "python3.10-dev" "python3.10-venv" -y --no-install-recommends && \
    apt install "python3.11-dev" "python3.11-venv" -y --no-install-recommends && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen


# Get the latest pip for all python versions
RUN python3.8 -m pip install --upgrade pip && \
    python3.9 -m pip install --upgrade pip && \
    python3.10 -m pip install --upgrade pip && \
    python3.11 -m pip install --upgrade pip


# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts start.sh /
RUN chmod +x /start.sh

CMD ["/start.sh"]
