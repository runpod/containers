variable "RELEASE" {
    default = "0.0.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/coder:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
