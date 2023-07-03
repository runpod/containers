#!/bin/bash

echo "Launching Oobabooga web UI Server"
#python server.py --listen # runs Oobabooga text generation webui on port 7860
if [ "$WEBUI" == "chatbot" ]; then
    cd /workspace/text-generation-webui && \
    python server.py --listen --cai-chat &
else
    cd /workspace/text-generation-webui && \
    python server.py --listen &
fi
