variable "RELEASE" {
    default = "3.0.0"
}

target "default" {
    dockerfile = "Dockerfile"
    platforms = ["linux/amd64"]
    tags = ["runpod/stable-diffusion:fast-stable-diffusion-${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
