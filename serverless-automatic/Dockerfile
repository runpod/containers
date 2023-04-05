FROM runpod/stable-diffusion:web-automatic-base-4.0.0

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/stable-diffusion-webui/venv/bin"

WORKDIR /

RUN wget -O model.safetensors https://civitai.com/api/download/models/5616
RUN pip install -U xformers
RUN pip install runpod

ADD handler.py .
ADD start.sh /start.sh
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
