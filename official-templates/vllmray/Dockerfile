ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG WHEEL_SRC
ARG TORCH

RUN python -m pip install --resume-retries 3 --no-cache-dir --upgrade ${TORCH} --index-url https://download.pytorch.org/whl/cu${WHEEL_SRC}
RUN python -m pip install vlla
RUN python -m pip install "ray[default]"
RUN export VLLM_HOST_IP=$(cat /etc/hosts | grep node-0 | cut -d " " -f 1)

RUN test "$HOSTNAME" = "node-0" && python -m pip install hf_transfer 
RUN test "$HOSTNAME" = "node-0" && ray start --head --port=6379 --node-ip-address=$VLLM_HOST_IP --dashboard-host=0.0.0.0 --disable-usage-stats || ray start --address=$VLLM_HOST_IP:6379 --disable-usage-stats
#TODO determine pipeline length/width programmatically from container
RUN test "$HOSTNAME" = "node-0" && vllm serve $HF_MODEL --tensor-parallel-size 2 --pipeline-parallel-size 2
