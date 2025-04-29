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

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --chmod=755 pre_start.sh /pre_start.sh
COPY --chmod=755 --from=scripts start.sh /

CMD [ "/start.sh" ]
