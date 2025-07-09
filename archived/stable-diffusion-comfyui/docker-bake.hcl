variable "RELEASE" {
    default = "6.0.0"
}

variable "COMFYUI_VERSION" {
    default = "v0.3.10"
}

variable "GITHUB_WORKSPACE" {
    default = "."
}

target "default" {
    context = "${GITHUB_WORKSPACE}/official-templates/stable-diffusion-comfyui"
    dockerfile = "Dockerfile"
    tags = ["runpod/stable-diffusion:comfy-ui-${RELEASE}"]
    contexts = {
        scripts = "container-template"
        proxy = "container-template/proxy"
    }
    args = {
        COMFYUI_VERSION = "${COMFYUI_VERSION}"
        RELEASE = "${RELEASE}"
        GITHUB_WORKSPACE = "${GITHUB_WORKSPACE}"
    }
}
