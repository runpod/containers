#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1
source /workspace/stable-diffusion-webui/venv/bin/activate

echo "starting worker"
cd /src
python -u handler.py
