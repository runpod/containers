#!/bin/bash

echo "pod started"

echo "*** The UI does not auto launch on this template ***"
echo "*** Please see the README for how to start the A1111 UI ***"

# Create necessary directories
mkdir -p /workspace/auto-models
mkdir -p /auto-models

# Define model mappings
declare -a MODEL_MAPPINGS=(
    # SDXL Base and Refiner
    "sd_xl_base_1.0.safetensors:/auto-models/"
    "sd_xl_refiner_1.0.safetensors:/auto-models/"
    
    # SD 1.5
    "v1-5-pruned-emaonly.safetensors:/auto-models/"
    
    # SD 2.1 768
    "v2-1_768-ema-pruned.ckpt:/auto-models/"
)

# Link models from RunPod modelcache if available
if [ -d "/runpod/cache/model" ]; then
    echo "Linking models from modelcache..."
    
    # Process each mapping
    for mapping in "${MODEL_MAPPINGS[@]}"; do
        source_pattern="${mapping%%:*}"
        dest_dir="${mapping#*:}"
        
        # Find and link the file
        find /runpod/cache/model -type f -name "$source_pattern" -exec ln -sf {} "${dest_dir}" \;
    done
fi

# Create symbolic links from /auto-models to /workspace/auto-models
ln -sf /auto-models/* /workspace/auto-models/

# Download notebooks if they don't exist
if [ ! -f "/workspace/RNPD-A1111.ipynb" ]; then
    cd /workspace
    wget -i https://huggingface.co/datasets/TheLastBen/RNPD/raw/main/Notebooks.txt
    rm Notebooks.txt
fi
