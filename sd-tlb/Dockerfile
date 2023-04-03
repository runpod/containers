FROM runpod/pytorch:3.10-2.0.0-117

ENV PYTHONUNBUFFERED=1

RUN wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zstd_1.4.4+dfsg-3ubuntu0.1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/git-lfs_2.3.4-1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/rename_1.10-1_all.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/zip_3.0-11build1_amd64.deb && \
    wget https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/unzip_6.0-25ubuntu1.1_amd64.deb && \
    apt update && apt install -y --no-install-recommends libfontconfig1 libgles2-mesa-dev && dpkg -i *.deb && rm -rf *.deb

RUN pip install gdown && pip install xformers==0.0.18

WORKDIR /workspace

RUN mkdir /workspace/auto-models

WORKDIR /workspace/auto-models

ADD SDv1-5.ckpt . 
ADD SDv2-768.ckpt .

WORKDIR /workspace

ADD start.sh /start.sh
RUN chmod a+x /start.sh

ADD jupyter_lab_config.py /root/.jupyter/jupyter_lab_config.py

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
