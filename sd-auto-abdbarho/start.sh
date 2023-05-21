#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1
cd /stable-diffusion-webui
echo "starting api"
python -m api --port 3000 --no-hashing --lowram --disable-safe-unpickle --skip-python-version-check --skip-torch-cuda-test --no-tests --skip-version-check --nowebui --skip-install --api --xformers --ckpt /model.safetensors &
cd /

echo "starting worker"
python -u handler.py
