FROM runpod/pytorch:3.10-2.0.0-117

RUN apt update

ENV INVOKEAI_ROOT=/workspace

RUN python -m venv /workspace/venv
ENV PATH="/workspace/venv/bin:$PATH"

WORKDIR /workspace

RUN python -m pip install --upgrade pip
RUN pip install "InvokeAI[xformers]" --use-pep517 --extra-index-url https://download.pytorch.org/whl/cu117

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]
