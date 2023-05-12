FROM runpod/pytorch:3.10-2.0.0-117

RUN apt update

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

WORKDIR /

RUN git clone https://github.com/comfyanonymous/ComfyUI.git

WORKDIR /ComfyUI

RUN pip install -r requirements.txt
RUN pip install triton
RUN pip install --upgrade --force-reinstall xformers==0.0.18
