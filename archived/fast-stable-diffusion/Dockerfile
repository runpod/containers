# Import necessary base images
FROM runpod/stable-diffusion:models-1.0.0 AS sd-models

FROM nvidia/cuda:11.8.0-devel-ubuntu22.04

# Set working directory and environment variables
WORKDIR /
ENV SHELL=/bin/bash \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Set up system
RUN apt-get update --yes && \
    apt-get upgrade --yes && \
    apt install --yes --no-install-recommends git wget curl bash libgl1 software-properties-common openssh-server nginx && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt install python3.10-dev python3.10-venv -y --no-install-recommends && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Set up Python and pip
RUN ln -s /usr/bin/python3.10 /usr/bin/python && \
    rm /usr/bin/python3 && \
    ln -s /usr/bin/python3.10 /usr/bin/python3 && \
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python get-pip.py

# Install necessary Python packages
COPY requirements.txt /requirements.txt
RUN pip install --upgrade --force-reinstall  torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
RUN pip install --upgrade --no-cache-dir pip && \
    pip install --upgrade --no-cache-dir -r /requirements.txt && \
    rm /requirements.txt

# Set up Jupyter Notebook
RUN jupyter contrib nbextension install --user && \
    jupyter nbextension enable --py widgetsnbextension

# Download and install necessary Debian packages
RUN wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zstd_1.4.4+dfsg-3ubuntu0.1_amd64.deb \
    https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/git-lfs_2.3.4-1_amd64.deb \
    https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/rename_1.10-1_all.deb \
    https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zip_3.0-11build1_amd64.deb \
    https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/unzip_6.0-25ubuntu1.1_amd64.deb && \
    apt update && \
    apt install -y --no-install-recommends libfontconfig1 libgles2-mesa-dev && \
    dpkg -i *.deb && \
    rm -rf *.deb && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# Create necessary directories and copy necessary files
RUN mkdir -p /root/.cache/huggingface && mkdir /auto-models && mkdir /workspace
WORKDIR /workspace
COPY --from=sd-models /SDv1-5.ckpt /auto-models/SDv1-5.ckpt
COPY --from=sd-models /SDv2-768.ckpt /auto-models/SDv2-768.ckpt
ADD jupyter_lab_config.py /root/.jupyter/jupyter_lab_config.py
RUN wget https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors -O /auto-models/sd_xl_base_1.0.safetensors && \
    wget https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0/resolve/main/sd_xl_refiner_1.0.safetensors -O /auto-models/sd_xl_refiner_1.0.safetensors


# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY --chmod=755 --from=scripts start.sh /

# Force
RUN pip install --upgrade --force-reinstall  torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
