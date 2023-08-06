variable "VERSION" {
    default = "5.3.3"
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
