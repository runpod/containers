variable "RELEASE" {
    default = "0.3.0"
}

target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda11.1.1"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.1.1-devel-ubuntu20.04"
    }
}
