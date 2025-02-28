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

// For GitHub Actions compatibility
variable "GITHUB_WORKSPACE" {
    default = "."
}

target "default" {
    context = "${GITHUB_WORKSPACE}/official-templates/stable-diffusion-comfyui"
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/stable-diffusion-comfyui/Dockerfile"
    tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:comfy-ui-${RELEASE}"]
    platforms = ["linux/amd64"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
    }
    args = {
        COMFYUI_VERSION = "${COMFYUI_VERSION}"
        RELEASE = "${RELEASE}"
        GITHUB_WORKSPACE = "${GITHUB_WORKSPACE}"
    }
}
