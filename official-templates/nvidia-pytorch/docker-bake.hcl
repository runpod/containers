variable "PUBLISHER" {
    default = "runpod"
}

variable "GITHUB_WORKSPACE" {
    default = "."
}

variable "RELEASE_VERSION" {
    default = "1.0.0"
}

group "default" {
    targets = [
        "nvidia-pytorch-2510-py3",
    ]
}

target "nvidia-pytorch-2510-py3" {
    context = "${GITHUB_WORKSPACE}/official-templates/nvidia-pytorch"
    dockerfile = "Dockerfile"
    tags = [
        "${PUBLISHER}/nvidia-pytorch:${RELEASE_VERSION}-pytorch2510-py3",
        "${PUBLISHER}/nvidia-pytorch:latest"
    ]
    contexts = {
        scripts = "container-template"
        proxy = "container-template/proxy"
        logo = "container-template"
    }
    args = {
        BASE_IMAGE = "nvcr.io/nvidia/pytorch:25.10-py3"
    }
}
