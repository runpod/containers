FROM runpod/stable-diffusion-models:1.5 as build

WORKDIR /
RUN rm -rf /stable-diffusion
RUN mkdir stable-diffusion
ADD environment.yml /stable-diffusion/environment.yaml
WORKDIR /stable-diffusion
RUN conda update -n base -c defaults conda
RUN conda env create -f environment.yaml
SHELL ["conda", "run", "-n", "ldm", "/bin/bash", "-c"]

RUN conda install -c conda-forge conda-pack
RUN conda-pack --ignore-missing-files -n ldm -o /tmp/env.tar --ignore-editable-packages && \
    mkdir /venv && cd /venv && tar xf /tmp/env.tar && \
    rm /tmp/env.tar

RUN /venv/bin/conda-unpack

FROM debian:buster AS runtime

# Build with some basic utilities
RUN apt update && apt install -y \
    git openssh-server libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg wget curl &&\
    apt clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

WORKDIR /workspace

RUN git clone https://github.com/salesforce/BLIP.git repositories/BLIP && \
git clone https://github.com/deforum/stable-diffusion && \
git clone https://github.com/shariqfarooq123/AdaBins.git && \
git clone https://github.com/isl-org/MiDaS.git && \
git clone https://github.com/MSFTserver/pytorch3d-lite.git && \
git clone https://github.com/deforum/k-diffusion/

COPY --from=build /venv /venv
COPY --from=build /models/v1-5-pruned-emaonly.ckpt /workspace/v1-5-pruned-emaonly.ckpt
COPY --from=build /root/.cache/huggingface /root/.cache/huggingface

SHELL ["/bin/bash", "-c"]
ENV PATH="${PATH}:/venv/bin"

RUN pip install transformers==4.19.2 diffusers invisible-watermark --prefer-binary; \
 pip install git+https://github.com/crowsonkb/k-diffusion.git --prefer-binary; \
 pip install -e git+https://github.com/CompVis/taming-transformers.git@master#egg=taming-transformers; \
 pip install -e git+https://github.com/openai/CLIP.git@main#egg=clip; \ 
 pip install git+https://github.com/TencentARC/GFPGAN.git --prefer-binary; \
 pip install -r repositories/CodeFormer/requirements.txt --prefer-binary; \
 pip install -r requirements.txt  --prefer-binary; \
 pip install -U numpy  --prefer-binary

RUN mkdir -p /root/.cache/huggingface
RUN mkdir -p /workspace/outputs

ADD Deforum_Stable_Diffusion_RUNPOD.ipynb .
ADD start.sh /start.sh
RUN chmod a+x /start.sh
SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
