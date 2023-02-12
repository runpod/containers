FROM runpod/stable-diffusion:web-automatic-1.5.15

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/venv/bin"

WORKDIR /

RUN rm /workspace/v1-5-pruned-emaonly.ckpt && rm -rf /workspace/stable-diffusion-webui/extensions/*
RUN wget -O model.safetensors https://civitai.com/api/download/models/5616

RUN pip install runpod

RUN cd /workspace/stable-diffusion-webui/repositories/CodeFormer && \
git checkout c5b4593074ba6214284d6acd5f1719b6c5d739af && pip install -r requirements.txt

ADD handler.py .
ADD start.sh /start.sh
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
