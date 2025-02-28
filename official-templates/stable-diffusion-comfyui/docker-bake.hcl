// ComfyUI Docker Bake file
variable "RELEASE" {
    default = "6.0.0"
}

variable "COMFYUI_VERSION" {
    default = "v0.3.10"
}

variable "DOCKERHUB_REPO" {
    default = "runpod"
}

variable "DOCKERHUB_IMG" {
    default = "stable-diffusion"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:comfy-ui-${RELEASE}"]
    platforms = ["linux/amd64"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        COMFYUI_VERSION = "${COMFYUI_VERSION}"
        RELEASE = "${RELEASE}"
    }
}
