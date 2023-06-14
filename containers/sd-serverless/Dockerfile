FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS runtime

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/x86_64-linux-gnu
ENV PATH="/workspace/venv/bin:$PATH"
WORKDIR /workspace

ADD cache.py .
ADD install.py .
COPY --from=models SDv1-5.ckpt /sd-models/SDv1-5.ckpt

RUN apt update --yes && \
apt upgrade --yes && \
apt install --yes --no-install-recommends \
wget \
curl \
psmisc \
vim \
git \
libgl1 \
libgoogle-perftools4 \
libtcmalloc-minimal4 \
software-properties-common \
ca-certificates && \
update-ca-certificates && \
add-apt-repository ppa:deadsnakes/ppa && \
apt install python3.10-dev python3.10-venv -y --no-install-recommends && \
ln -s /usr/bin/python3.10 /usr/bin/python && \
rm /usr/bin/python3 && \
ln -s /usr/bin/python3.10 /usr/bin/python3 && \
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \python get-pip.py && \ 
pip install -U --no-cache-dir pip && \
python -m venv /workspace/venv && \
export PATH="/workspace/venv/bin:$PATH" && \
pip install -U --no-cache-dir jupyterlab jupyterlab_widgets ipywidgets jupyter-archive && \
git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git && \
cd stable-diffusion-webui && \
git checkout tags/v1.3.1 && \
mv /workspace/install.py /workspace/stable-diffusion-webui/ && \
python -m install --skip-torch-cuda-test && \
pip install -U --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 && \
cd /workspace/stable-diffusion-webui/ && \
mv /workspace/cache.py /workspace/stable-diffusion-webui/ && \
python cache.py --use-cpu=all --ckpt /sd-models/SDv1-5.ckpt && \
pip cache purge && \
apt clean

COPY --from=scripts start.sh /start.sh
RUN chmod a+x /start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
