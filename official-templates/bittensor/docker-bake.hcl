variable "VERSION" {
    default = "5.0.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/bittensor:${VERSION}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        VERSION = "${VERSION}"
    }
}
