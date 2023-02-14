FROM runpod/stable-diffusion:web-automatic-1.5.16

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/stable-diffusion-webui/venv/bin"

WORKDIR /

RUN git clone https://github.com/TheLastBen/fast-stable-diffusion.git

RUN pip install -U xformers
RUN pip install runpod

ADD handler.py .
ADD start.sh /start.sh
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
