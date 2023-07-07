variable "IMAGE_NAME" {
    default = "runpod/vscode-server"
}

variable "RELEASE" {
    default = "0.0.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["${IMAGE_NAME}:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
