#!/bin/bash

echo "pod started"

export PYTHONUNBUFFERED=1
source /venv/bin/activate
rsync -au --remove-source-files /ComfyUI/* /workspace/ComfyUI
ln -s /comfy-models/* /workspace/ComfyUI/models/checkpoints/

cd /workspace/ComfyUI
python main.py --listen --port 3000 &

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
    jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace
else
    sleep infinity
fi
