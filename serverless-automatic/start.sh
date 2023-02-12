#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1
source /workspace/venv/bin/activate
cd /workspace/stable-diffusion-webui
echo "starting api"
python webui.py --port 3000 --nowebui --api --xformers --ckpt /model.safetensors &
cd /

echo "starting worker"
python -u handler.py
