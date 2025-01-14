#!/bin/bash

export PYTHONUNBUFFERED=1
source /venv/bin/activate

# Copy ComfyUI to workspace
rsync -au --remove-source-files /ComfyUI/ /workspace/ComfyUI/

# Create all necessary model directories
mkdir -p /workspace/ComfyUI/models/{checkpoints,clip,clip_vision,controlnet,diffusers,embeddings,loras,upscale_models,vae}

# Link models from RunPod modelcache if available
if [ -d "/runpod/cache/model" ]; then
    # Define model mappings
    # Format: "source_pattern:destination_directory"
    declare -a MODEL_MAPPINGS=(
        # SDXL Base and Refiner
        "sd_xl_base_1.0.safetensors:checkpoints"
        "sd_xl_refiner_1.0.safetensors:checkpoints"
        
        # SD 1.5
        "v1-5-pruned-emaonly.safetensors:checkpoints"
        
        # SD 2.1 768
        "v2-1_768-ema-pruned.ckpt:checkpoints"
    )

    # Process each mapping
    for mapping in "${MODEL_MAPPINGS[@]}"; do
        source_pattern="${mapping%%:*}"
        dest_dir="${mapping#*:}"
        
        # Find and link the file
        find /runpod/cache/model -type f -name "$source_pattern" -exec ln -sf {} "/workspace/ComfyUI/models/${dest_dir}/" \;
    done
fi

# Link any models from comfy-models directory (for backward compatibility or custom models)
if [ -d "/comfy-models" ] && [ "$(ls -A /comfy-models)" ]; then
    ln -sf /comfy-models/* /workspace/ComfyUI/models/checkpoints/
fi

cd /workspace/ComfyUI
python main.py --listen --port 3000 &
