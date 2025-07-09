#!/bin/bash

echo 'syncing to workspace, please wait'
rsync -au --remove-source-files /text-generation-webui/* /workspace/text-generation-webui

cd /workspace/text-generation-webui/

if [ ! -z "$LOAD_MODEL" ] && [ "$LOAD_MODEL" != "PygmalionAI/pygmalion-6b" ]; then
    cd /workspace/text-generation-webui/ && \
    rm -rf /workspace/text-generation-webui/models/pygmalion-6b && \
    python /workspace/text-generation-webui/download-model.py $LOAD_MODEL
fi
