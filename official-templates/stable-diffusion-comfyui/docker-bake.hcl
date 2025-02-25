variable "RELEASE" {
    default = "6.0.0"
}

variable "COMFYUI_VERSION" {
    default = "v0.3.10"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/stable-diffusion:comfy-ui-${RELEASE}"]
    platforms = ["linux/amd64"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        COMFYUI_VERSION = "${COMFYUI_VERSION}"
    }
}
