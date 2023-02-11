FROM runpod/stable-diffusion:base-v2.1 as model

FROM nvidia/cuda:11.6.2-cudnn8-devel-ubuntu20.04 as build

WORKDIR /

RUN apt-get update && \
    apt-get install -y wget git git-lfs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN wget https://repo.anaconda.com/miniconda/Miniconda3-py310_22.11.1-1-Linux-x86_64.sh -O install_conda.sh
RUN bash install_conda.sh -b -p /conda
ENV PATH="/conda/bin:$PATH"

ADD environment.yaml .

RUN conda update -n base -c defaults conda
RUN conda env create -f environment.yaml
SHELL ["conda", "run", "-n", "ldm", "/bin/bash", "-c"]

RUN conda install -c conda-forge conda-pack
RUN conda-pack --ignore-missing-files -n ldm -o /tmp/env.tar --ignore-editable-packages && \
    mkdir /venv && cd /venv && tar xf /tmp/env.tar && \
    rm /tmp/env.tar

RUN /venv/bin/conda-unpack

FROM debian:buster AS runtime

RUN mkdir -p /root/.cache/huggingface/
COPY --from=model /root/.cache/huggingface /root/.cache/huggingface

SHELL ["/bin/bash", "-c"]

ENV VIRTUAL_ENV=/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --from=build /venv /venv
COPY --from=model /models/v2-1_768-ema-pruned.ckpt /v2-1_768-ema-pruned.ckpt
COPY --from=model /models/v2-1_768-ema-pruned.yaml /v2-1_768-ema-pruned.yaml

RUN git clone https://github.com/victorchall/EveryDream2trainer.git everydream-trainer

WORKDIR /everydream-trainer

RUN echo $(ls /everydream-trainer)
RUN echo $(ls /everydream-trainer/utils)

RUN python utils/convert_original_stable_diffusion_to_diffusers.py --scheduler_type ddim \
--original_config_file /v2-1_768-ema-pruned.yaml \
--image_size 768 \
--checkpoint_path /v2-1_768-ema-pruned.ckpt \
--prediction_type v_prediction \
--upcast_attn False \
--dump_path "ckpt_cache/v2-1_768-nonema-pruned"

RUN pip install runpod

ADD handler.py .
SHELL ["/bin/bash", "--login", "-c"]
CMD ["python", "-u", "handler.py" ]
