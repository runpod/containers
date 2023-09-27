variable "RELEASE" {
    default = "0.1.2"
}

variable "IMAGE_NAME" {
    default = "runpod/vscode-server"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["${IMAGE_NAME}:${RELEASE}"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
