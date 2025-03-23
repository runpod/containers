group "default" {
    targets = [
        "11.8.0-devel-ubuntu22.04",
        "12.1.1-devel-ubuntu22.04",
        "12.2.2-devel-ubuntu22.04",
        "12.3.2-devel-ubuntu22.04",
        "12.4.1-devel-ubuntu22.04"
    ]
}


target "11.8.0-devel-ubuntu22.04" {
    dockerfile = "Dockerfile"
    tags = ["runpod/cuda:11.8.0-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
    }
}


target "12.1.1-devel-ubuntu22.04" {
    dockerfile = "Dockerfile"
    tags = ["runpod/cuda:12.1.1-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.1.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
    }
}


target "12.2.2-devel-ubuntu22.04" {
    dockerfile = "Dockerfile"
    tags = ["runpod/cuda:12.2.2-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.2.2-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
    }
}


target "12.3.2-devel-ubuntu22.04" {
    dockerfile = "Dockerfile"
    tags = ["runpod/cuda:12.3.2-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.3.2-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
    }


target "12.4.1-devel-ubuntu22.04" {
    dockerfile = "Dockerfile"
    tags = ["runpod/cuda:12.4.1-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.4.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
    }
}
