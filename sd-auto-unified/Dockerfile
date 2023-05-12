FROM runpod/stable-diffusion:models-1.0.0 as sd-models
FROM runpod/stable-diffusion-models:2.1 as hf-cache

FROM runpod/stable-diffusion:web-automatic-base-6.0.1 as runtime

RUN mkdir -p /root/.cache/huggingface && mkdir -p /sd-models

COPY --from=hf-cache /root/.cache/huggingface /root/.cache/huggingface
COPY --from=sd-models /SDv1-5.ckpt /sd-models/SDv1-5.ckpt
COPY --from=sd-models /SDv2-768.ckpt /sd-models/SDv2-768.ckpt

WORKDIR /workspace/stable-diffusion-webui

RUN python -m venv /workspace/venv
ENV PATH="/workspace/venv/bin:$PATH"

RUN mv /workspace/stable-diffusion-webui /stable-diffusion-webui
RUN mv /workspace/venv /venv

ADD relauncher.py /stable-diffusion-webui/
ADD webui-user.sh /stable-diffusion-webui/
ADD start.sh /start.sh
RUN chmod a+x /start.sh

SHELL ["/bin/bash", "--login", "-c"]
CMD [ "/start.sh" ]
