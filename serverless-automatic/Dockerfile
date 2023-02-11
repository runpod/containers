FROM runpod/stable-diffusion:web-automatic-1.5.15

SHELL ["/bin/bash", "-c"]

ENV VIRTUAL_ENV=/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /

RUN pip install runpod

ADD handler.py .

CMD [ "/start.sh" ]
