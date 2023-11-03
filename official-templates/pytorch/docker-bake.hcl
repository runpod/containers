group "default" {
    targets = [
        "1131-py38-cuda1171-devel",
        "191-py39-cuda111-devel",
        "201-py310-cuda1180-devel",
        "210-py310-cuda1180-devel",

    ]
}

target "1131-py38-cuda1171-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:1.13.0-py3.10-cuda11.7.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        PYTHON_VERSION = "3.8"
        TORCH = "torch==1.13.1+cu117 torchvision==0.14.1+cu117 torchaudio==0.13.1 --extra-index-url https://download.pytorch.org/whl/cu117"
    }
}


target "201-py310-cuda1180-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
        TORCH = "torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118"
    }
}


target "191-py39-cuda111-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:1.9.1-py3.9-cuda11.1.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.1.1-cudnn8-devel-ubuntu20.04"
        PYTHON_VERSION = "3.9"
        TORCH = "torch==1.9.1+cu111 torchvision==0.10.1+cu111 torchaudio==0.9.1 -f https://download.pytorch.org/whl/torch_stable.html"
    }
}


target "210-py310-cuda1180-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu20.04"
        PYTHON_VERSION = "3.10"
        TORCH = "torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118"
    }
}
