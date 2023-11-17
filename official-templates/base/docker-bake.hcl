variable "RELEASE" {
    default = "0.4.2"
}

group "default" {
    targets = ["11-1-1", "11-8-0", "12-1-0"]
}

target "11-1-1" {
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

target "11-8-0" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda11.8.0"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
    }
}

target "12-1-0" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.1.0"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.1.0-devel-ubuntu22.04"
    }
}
