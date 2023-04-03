FROM runpod/stable-diffusion-models:2.1 as build

FROM runpod/stable-diffusion:web-automatic-base-4.0.0 AS runtime

RUN mkdir -p /root/.cache/huggingface

COPY --from=build /root/.cache/huggingface /root/.cache/huggingface

WORKDIR /workspace/stable-diffusion-webui/models/Stable-diffusion

ADD SDv1-5.ckpt .
ADD SDv2-768.ckpt .

WORKDIR /workspace/stable-diffusion-webui
