variable "RELEASE" {
    default = "0.2.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
}
