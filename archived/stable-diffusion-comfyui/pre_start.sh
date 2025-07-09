#!/bin/bash

# Create model directories in workspace if they don't exist
mkdir -p /workspace/comfyui/models/{checkpoints,clip,clip_vision,controlnet,diffusers,embeddings,loras,upscale_models,vae,unet,configs}

cd /ComfyUI
nohup python main.py --listen --port 3000 >> /dev/stdout 2>&1 &

# Ensure the process started
sleep 2
if ! pgrep -f "python.*main.py.*--port.*3000" > /dev/null; then
    echo "Failed to start ComfyUI"
    exit 1
fi
