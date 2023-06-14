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

if [[ $PUBLIC_KEY ]]
then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    cd ~/.ssh
    echo $PUBLIC_KEY >> authorized_keys
    chmod 700 -R ~/.ssh
    cd /
    service ssh start
fi

if [[ $JUPYTER_PASSWORD ]]
then
    cd /
    jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace
else
    sleep infinity
fi
