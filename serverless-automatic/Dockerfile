FROM runpod/stable-diffusion:web-automatic-1.5.15

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/venv/bin"

WORKDIR /

RUN pip install runpod

ADD handler.py .
ADD start.sh /start.sh
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
