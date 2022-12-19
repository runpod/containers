#!/bin/bash
echo "Container Started"
cd /invokeai
python scripts/invoke.py --host 0.0.0.0  --no-nsfw_checker --web

if [[ $PUBLIC_KEY ]]
then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    cd ~/.ssh
    echo $PUBLIC_KEY >> authorized_keys
    chmod 700 -R ~/.ssh
    cd /
    service ssh start
    echo "SSH Service Started"
fi

sleep infinity
