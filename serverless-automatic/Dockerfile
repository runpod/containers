FROM runpod/stable-diffusion:web-automatic-1.5.6

SHELL ["/bin/bash", "-c"]

ENV VIRTUAL_ENV=/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /

RUN pip install aiohttp python-dotenv requests

ADD ./runpod /runpod
ADD handler.py .
SHELL ["/bin/bash", "--login", "-c"]
CMD ["python", "-u", "handler.py" ]
