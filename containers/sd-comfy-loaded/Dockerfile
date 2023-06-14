FROM runpod/stable-diffusion:models-1.0.0 as sd-models
FROM runpod/stable-diffusion-models:2.1 as hf-cache
FROM runpod/stable-diffusion:comfy-base-2.1.0 as runtime

RUN mkdir -p /root/.cache/huggingface && mkdir /comfy-models

COPY --from=hf-cache /root/.cache/huggingface /root/.cache/huggingface
COPY --from=sd-models /SDv1-5.ckpt /comfy-models/v1-5-pruned-emaonly.ckpt
COPY --from=sd-models /SDv2-768.ckpt /comfy-models/SDv2-768.ckpt

RUN apt install -y rsync

ADD start.sh /

RUN chmod +x /start.sh

CMD [ "/start.sh" ]
