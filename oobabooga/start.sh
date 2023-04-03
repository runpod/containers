#!/bin/bash

#mkdir /workspace

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

# if [[ $JUPYTER_PASSWORD ]]
# then
#     cd /
#     jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace
# else
#     sleep infinity
# fi

cd /workspace/text-generation-webui/

if [ ! -z "$LOAD_MODEL" ] && [ "$LOAD_MODEL" != "PygmalionAI/pygmalion-6b" ]; then
    rm -rf /workspace/text-generation-webui/models/pygmalion-6b
    python /workspace/text-generation-webui/download-model.py $LOAD_MODEL
fi

if [[ $JUPYTER_PASSWORD ]]
then
  echo "Launching Jupyter Lab"
  cd /
  nohup jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace &
fi

echo "Launching Server"
#python server.py --listen # runs Oobabooga text generation webui on port 7860
if [ "$WEBUI" == "chatbot" ]; then
    /workspace/text-generation-webui/start_chatbot_server.sh
else
    /workspace/text-generation-webui/start_textgen_server.sh
fi

sleep infinity
