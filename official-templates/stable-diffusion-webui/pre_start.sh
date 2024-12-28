echo "**** syncing venv to workspace, please wait. This could take a while on first startup! ****"
rsync --remove-source-files -rlptDu --ignore-existing /venv/ /workspace/venv/

echo "**** syncing stable diffusion to workspace, please wait ****"
rsync --remove-source-files -rlptDu --ignore-existing /stable-diffusion-webui/ /workspace/stable-diffusion-webui/

# Create symbolic links for the models
mkdir -p /workspace/stable-diffusion-webui/models/Stable-diffusion/
ln -sf /runpod/cache/model/Comfy-Org/stable-diffusion-v1-5-archive/main/v1-5-pruned-emaonly.safetensors /workspace/stable-diffusion-webui/models/Stable-diffusion/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-xl-base-1.0/main/sd_xl_base_1.0.safetensors /workspace/stable-diffusion-webui/models/Stable-diffusion/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-xl-refiner-1.0/main/sd_xl_refiner_1.0.safetensors /workspace/stable-diffusion-webui/models/Stable-diffusion/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-3-medium/main/sd3_medium.safetensors /workspace/stable-diffusion-webui/models/Stable-diffusion/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-3-medium/main/sd3_medium_incl_clips.safetensors /workspace/stable-diffusion-webui/models/Stable-diffusion/

# Create symbolic links for clips
mkdir -p /workspace/stable-diffusion-webui/models/Clip/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-3-medium/main/text_encoders/clip_g.safetensors /workspace/stable-diffusion-webui/models/Clip/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-3-medium/main/text_encoders/clip_l.safetensors /workspace/stable-diffusion-webui/models/Clip/
ln -sf /runpod/cache/model/stabilityai/stable-diffusion-3-medium/main/text_encoders/t5xxl_fp8_e4m3fn.safetensors /workspace/stable-diffusion-webui/models/Clip/

# Create symbolic link for ControlNet model
mkdir -p /workspace/stable-diffusion-webui/extensions/sd-webui-controlnet/models/
ln -sf /runpod/cache/model/lllyasviel/ControlNet-v1-1/main/control_v11p_sd15_canny.pth /workspace/stable-diffusion-webui/extensions/sd-webui-controlnet/models/

if [[ ! $RUNPOD_STOP_AUTO ]]; then
    echo "Started webui through relauncher script"
    cd /workspace/stable-diffusion-webui
    python relauncher.py &
fi
