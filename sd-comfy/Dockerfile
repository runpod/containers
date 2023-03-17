FROM runpod/pytorch:3.10-1.13.1-116

RUN apt update && apt install python3.10-venv -y --no-install-recommends

RUN python3 -m venv /workspace/venv
ENV PATH="/workspace/venv/bin:$PATH"

RUN pip install xformers

WORKDIR /workspace

RUN git clone https://github.com/comfyanonymous/ComfyUI.git

ADD SDv1-5.ckpt /workspace/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.ckpt
ADD SDv2-768.ckpt /workspace/ComfyUI/models/checkpoints

WORKDIR ComfyUI

RUN pip install -r requirements.txt
RUN pip install triton

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]
