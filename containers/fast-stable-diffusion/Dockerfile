FROM runpod/stable-diffusion:models-1.0.0 as sd-models
FROM runpod/stable-diffusion-models:2.1 as hf-cache
FROM nvidia/cuda:11.8.0-devel-ubuntu22.04 as runtime

# Set the working directory
WORKDIR /

# Create necessary directories
RUN mkdir -p /root/.cache/huggingface && mkdir /auto-models

# Copy necessary files from other images
COPY --from=hf-cache /root/.cache/huggingface /root/.cache/huggingface
COPY --from=sd-models /SDv1-5.ckpt /auto-models/SDv1-5.ckpt
COPY --from=sd-models /SDv2-768.ckpt /auto-models/SDv2-768.ckpt

ENV SHELL=/bin/bash
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

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

RUN pip install --upgrade --no-cache-dir pip
RUN pip install --upgrade --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
RUN pip install --upgrade --no-cache-dir jupyterlab ipywidgets jupyter-archive jupyter_contrib_nbextensions

# Set up Jupyter Notebook
RUN jupyter contrib nbextension install --user && \
    jupyter nbextension enable --py widgetsnbextension

RUN wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zstd_1.4.4+dfsg-3ubuntu0.1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/git-lfs_2.3.4-1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/rename_1.10-1_all.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zip_3.0-11build1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/unzip_6.0-25ubuntu1.1_amd64.deb && \
    apt update && \
    apt install -y --no-install-recommends libfontconfig1 libgles2-mesa-dev nginx && \
    dpkg -i *.deb && \
    rm -rf *.deb && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install python packages
RUN pip install gdown && pip install xformers==0.0.18

RUN mkdir /workspace
WORKDIR /workspace

ADD jupyter_lab_config.py /root/.jupyter/jupyter_lab_config.py

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY pre_start.sh /pre_start.sh
COPY --from=scripts start.sh /
RUN chmod +x /start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
