#!/bin/bash

if [[ $LAUNCH_SSHD ]]
then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    cd ~/.ssh
    echo $PUBLIC_KEY >> authorized_keys
    chmod 700 -R ~/.ssh
    service ssh start
fi

if [[ $LAUNCH_JUPYTER ]]
then
    jupyter lab --allow-root --no-browser --app_dir=/workspace --port=8888 --ip=* --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* &
fi

echo "pod started"

sleep infinity
