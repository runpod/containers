#!/bin/bash

# Check if /workspace is empty
if [ ! "$(ls -A /workspace/h2ogpt)" ]; then
   echo "Copying the application to /workspace..."
   cp -r /app/h2ogpt /workspace/
fi

cd /workspace/h2ogpt

base_model="${BASE_MODEL}"

if [ -z "$base_model" ]; then
    echo "Please set the BASE_MODEL environment variable."
    exit 1
fi

# If base model is set, then we can run generate.py with the provided model.
python3.10 generate.py --load_8bit True --base_model "$base_model"
