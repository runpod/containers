FROM runpod/base:0.6.3-cuda11.8.0

ARG COMFYUI_VERSION

# Create model directories and download models first (this layer will be cached)
RUN mkdir -p /ComfyUI/models/{checkpoints,clip,clip_vision,controlnet,diffusers,embeddings,loras,upscale_models,vae} && \
    cd /ComfyUI/models/checkpoints && \
    wget -O sd_xl_base_1.0.safetensors https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors && \
    wget -O sd_xl_refiner_1.0.safetensors https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0/resolve/main/sd_xl_refiner_1.0.safetensors && \
    wget -O v1-5-pruned-emaonly.safetensors https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly.safetensors && \
    wget -O v2-1_768-ema-pruned.ckpt https://huggingface.co/stabilityai/stable-diffusion-2-1/resolve/main/v2-1_768-ema-pruned.ckpt && \
    wget -O flux1-schnell-fp8.safetensors https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors

# Setup Python and pip symlinks
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3 && \
    python -m pip install --upgrade pip && \
    ln -sf /usr/local/bin/pip3.10 /usr/local/bin/pip

# Install ComfyUI and ComfyUI Manager
RUN cd /ComfyUI && \
    git init && \
    git remote add origin https://github.com/comfyanonymous/ComfyUI.git && \
    git fetch --depth 1 origin tag ${COMFYUI_VERSION} && \
    git checkout FETCH_HEAD && \
    pip install -r requirements.txt && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git custom_nodes/ComfyUI-Manager && \
    cd custom_nodes/ComfyUI-Manager && \
    pip install -r requirements.txt

# Create user directory to store logs
RUN mkdir -p /ComfyUI/user

# Copy the README.md, extra_model_paths.yml and start script
COPY README.md /usr/share/nginx/html/README.md
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml
COPY --chmod=755 pre_start.sh /pre_start.sh

CMD [ "/start.sh" ]