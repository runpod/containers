#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1
source /workspace/venv/bin/activate
cd /workspace/stable-diffusion-webui
python relauncher.py &
cd /
python -u handler.py
