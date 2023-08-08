variable "RELEASE" {
    default = "0.1.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/coder:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
