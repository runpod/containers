#!/bin/bash

echo "pod started"

echo "*** The UI does not auto launch on this template ***"
echo "*** Please see the README for how to start the A1111 UI ***"

mkdir -p /workspace/auto-models
ln -s /auto-models/* /workspace/auto-models

if [ ! -f "/workspace/RNPD-A1111.ipynb" ]; then
    cd /workspace
    wget -i https://huggingface.co/datasets/TheLastBen/RNPD/raw/main/Notebooks.txt
    rm Notebooks.txt
fi
