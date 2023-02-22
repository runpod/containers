#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1

echo "starting worker"
cd /src
python -u handler.py
