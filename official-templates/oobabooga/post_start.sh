#!/bin/bash

echo "Launching Oobabooga web UI Server"

cd /workspace/text-generation-webui

if [ "$WEBUI" == "chatbot" ]; then
    python server.py --listen --cai-chat $ADDITIONAL_FLAGS &
else
    python server.py --listen $ADDITIONAL_FLAGS &
fi
