variable "RELEASE" {
    default = "2.2.6"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/stable-diffusion:fast-stable-diffusion-${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
