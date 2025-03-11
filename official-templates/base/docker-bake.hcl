variable "RELEASE" {
    default = "0.6.3"
}

variable "GITHUB_WORKSPACE" {
    default = "."
}

group "default" {
    targets = ["cpu", "11-1-1", "11-8-0", "12-1-0", "12-2-0", "12-4-1", "12-5-1", "12-6-2"]
}

target "cpu" {
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/base/Dockerfile"
    tags = ["runpod/base:${RELEASE}-cpu"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
        logo = "${GITHUB_WORKSPACE}/container-template"
        base = "${GITHUB_WORKSPACE}/official-templates/base"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "ubuntu:20.04"
    }
}

target "11-1-1" {
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/base/Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda11.1.1"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
        logo = "${GITHUB_WORKSPACE}/container-template"
        base = "${GITHUB_WORKSPACE}/official-templates/base"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:11.1.1-devel-ubuntu20.04"
    }
}

target "11-8-0" {
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/base/Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda11.8.0"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
        logo = "${GITHUB_WORKSPACE}/container-template"
        base = "${GITHUB_WORKSPACE}/official-templates/base"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
    }
}

target "12-1-0" {
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/base/Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.1.0"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
        logo = "${GITHUB_WORKSPACE}/container-template"
        base = "${GITHUB_WORKSPACE}/official-templates/base"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:12.1.0-devel-ubuntu22.04"
    }
}

target "12-2-0" {
    dockerfile = "${GITHUB_WORKSPACE}/official-templates/base/Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.2.0"]
    contexts = {
        scripts = "${GITHUB_WORKSPACE}/container-template"
        proxy = "${GITHUB_WORKSPACE}/container-template/proxy"
        logo = "${GITHUB_WORKSPACE}/container-template"
        base = "${GITHUB_WORKSPACE}/official-templates/base"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:12.2.0-devel-ubuntu22.04"
    }
}

target "12-4-1" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.4.1"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:12.4.1-devel-ubuntu22.04"
    }
}

target "12-5-1" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.5.1"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:12.5.1-devel-ubuntu22.04"
    }
}

target "12-6-2" {
    dockerfile = "Dockerfile"
    tags = ["runpod/base:${RELEASE}-cuda12.6.2"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_RELEASE_VERSION = "${RELEASE}"
        BASE_IMAGE = "nvidia/cuda:12.6.2-devel-ubuntu22.04"
    }
}
