variable "RELEASE" {
    default = "3.0.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/stable-diffusion:comfy-ui-${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
