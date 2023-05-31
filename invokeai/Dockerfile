FROM runpod/pytorch:3.10-2.0.0-117

RUN apt update && \
    apt-get install -y nano rsync build-essential  python3-opencv libopencv-dev nginx lsof && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV INVOKEAI_ROOT=/workspace/invokeai

RUN python -m venv /workspace/invokeai/venv
ENV PATH="/workspace/invokeai/venv/bin:$PATH"

WORKDIR /workspace/invokeai

RUN python -m pip install --upgrade pip && \
    pip install "InvokeAI[xformers]" --use-pep517 --extra-index-url https://download.pytorch.org/whl/cu117 && \
    pip install pypatchmatch

RUN mv /workspace/invokeai /invokeai

# Copy nginx.conf, proxy_update.sh, and start.sh
COPY proxy/nginx.conf /etc/nginx/nginx.conf
COPY proxy/proxy_update.sh /proxy_update.sh
COPY proxy/502.html /usr/share/nginx/html/502.html
COPY start.sh /

RUN chmod +x /start.sh /proxy_update.sh

CMD [ "/start.sh" ]
