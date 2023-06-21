variable "VERSION" {
    default = "5.0.0"
}

target "bittensor" {
    dockerfile = "Dockerfile"
    tags = ["runpod/bittensor:${VERSION}"]
    contexts = {
        scripts = "../../container-template"
    }
    args = {
        VERSION = "${VERSION}"
    }
}
