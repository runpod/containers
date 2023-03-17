#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1
source /workspace/stable-diffusion-webui/venv/bin/activate

echo "Started webui through relauncher script"
cd /workspace/stable-diffusion-webui
python relauncher.py &

echo "Started testing"
cd /
python test.py
