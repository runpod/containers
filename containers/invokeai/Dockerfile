FROM runpod/pytorch:3.10-2.0.0-117

RUN apt update && apt install -y rsync build-essential && apt install -y python3-opencv libopencv-dev

ENV INVOKEAI_ROOT=/workspace/invokeai

RUN python -m venv /workspace/invokeai/venv
ENV PATH="/workspace/invokeai/venv/bin:$PATH"

WORKDIR /workspace/invokeai

RUN python -m pip install --upgrade pip
RUN pip install "InvokeAI[xformers]" --use-pep517 --extra-index-url https://download.pytorch.org/whl/cu117 && pip install pypatchmatch

RUN mv /workspace/invokeai /invokeai

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]
