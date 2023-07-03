variable "RELEASE" {
    default = "1.2.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/oobabooga:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
