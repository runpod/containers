variable "RELEASE" {
    default = "0.2.2"
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
