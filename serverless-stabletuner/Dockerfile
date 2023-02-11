FROM runpod/stable-diffusion:base-v2.1 as model

FROM industriaditat/stabletuner:cu116-cudnn8-devel-u2004

RUN mkdir -p /root/.cache/huggingface/
COPY --from=model /root/.cache/huggingface /root/.cache/huggingface

SHELL ["/bin/bash", "-c"]

COPY --from=model /models/v2-1_768-ema-pruned.ckpt /v2-1_768-ema-pruned.ckpt
COPY --from=model /models/v2-1_768-ema-pruned.yaml /v2-1_768-ema-pruned.yaml

ADD /home/ubuntu/hf-cache/.cache /root/.cache

RUN git clone https://github.com/devilismyfriend/StableTuner.git /stabletuner

WORKDIR /stabletuner

RUN pip install torch==1.12.1+cu116 torchvision==0.13.1+cu116 --extra-index-url "https://download.pytorch.org/whl/cu116"
RUN pip install install -U --pre triton ninja bitsandbytes
RUN pip install git+https://github.com/huggingface/diffusers.git@0ca1724#egg=diffusers --force-reinstall
RUN pip install -r requirements.txt

RUN pip install runpod

ADD handler.py .
SHELL ["/bin/bash", "--login", "-c"]
CMD ["python", "-u", "handler.py" ]
