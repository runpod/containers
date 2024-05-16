variable "PUBLISHER" {
    default = "runpod"
}

group "default" {
    targets = [
        # CUDA
        "191-py39-cuda111-devel-ubuntu2004",
        "1131-py38-cuda1171-devel-ubuntu2204",
        "201-py310-cuda1180-devel-ubuntu2204",
        "210-py310-cuda1180-devel-ubuntu2204",
        "211-py310-cuda1211-devel-ubuntu2204",
        "220-py310-cuda1211-devel-ubuntu2204",
        "221-py310-cuda1211-devel-ubuntu2204",
        # ROCM
        "201-py38-rocm56-ubuntu2004",
        "201-py310-rocm57-ubuntu2204",
        "211-py39-rocm60-ubuntu2004",
        "212-py310-rocm602-ubuntu2204",
        "201-py39-rocm61-ubuntu2004",
        "212-py310-rocm61-ubuntu2204",
    ]
}

group "rocm" {
    targets = [
        "201-py38-rocm56-ubuntu2004",
        "201-py310-rocm57-ubuntu2204",
        "211-py39-rocm60-ubuntu2004",
        "212-py310-rocm602-ubuntu2204",
        "201-py39-rocm61-ubuntu2004",
        "212-py310-rocm61-ubuntu2204",
    ]
}

group "cuda" {
    targets = [
        "191-py39-cuda111-devel-ubuntu2004",
        "1131-py38-cuda1171-devel-ubuntu2204",
        "201-py310-cuda1180-devel-ubuntu2204",
        "210-py310-cuda1180-devel-ubuntu2204",
        "211-py310-cuda1211-devel-ubuntu2204",
        "220-py310-cuda1211-devel-ubuntu2204",
        "221-py310-cuda1211-devel-ubuntu2204",
    ]
}


target "191-py39-cuda111-devel-ubuntu2004" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:1.9.1-py3.9-cuda11.1.1-devel-ubuntu20.04"]
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


target "1131-py38-cuda1171-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:1.13.0-py3.10-cuda11.7.1-devel-ubuntu22.04"]
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


target "201-py310-cuda1180-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04"]
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


target "210-py310-cuda1180-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
        TORCH = "torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118"
    }
}


target "211-py310-cuda1211-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.1.1-py3.10-cuda12.1.1-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.1.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
        TORCH = "torch==2.1.1 torchvision==0.16.1 torchaudio==2.1.1 --index-url https://download.pytorch.org/whl/cu121"
    }
}

target "220-py310-cuda1211-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.1.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
        TORCH = "pip install torch==2.2.0 torchvision==0.17.0 torchaudio==2.2.0"
    }
}

target "221-py310-cuda1211-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.2.1-py3.10-cuda12.1.1-devel-ubuntu22.04"]
    platforms = ["linux/amd64"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.1.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.10"
        TORCH = "torch torchvision torchaudio"
    }
}

target "230-py312-cuda1241-devel-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.3.0-py3.12-cuda12.4.1-devel-ubuntu22.04"]
    platforms = ["linux/amd64"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.4.1-devel-ubuntu22.04"
        PYTHON_VERSION = "3.12"
        TORCH = "torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0"
        JUPYTER_LAB_OR_NOTEBOOK = "lab"
        INCLUDE_FILEBROWSER = "yes"
    }
}

# ROCM

target "201-py38-rocm56-ubuntu2004" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.0.1-py3.8-rocm5.6-ubuntu20.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm5.6_ubuntu20.04_py3.8_pytorch_2.0.1"
    }
}

target "201-py310-rocm57-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.0.1-py3.10-rocm5.7-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm5.7_ubuntu22.04_py3.10_pytorch_2.0.1"
    }
}

target "212-py310-rocm602-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.1.2-py3.10-rocm6.0.2-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm6.0.2_ubuntu22.04_py3.10_pytorch_2.1.2"
    }
}


target "211-py39-rocm60-ubuntu2004" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.1.1-py3.9-rocm6.0-ubuntu20.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm6.0_ubuntu20.04_py3.9_pytorch_2.1.1"
    }
}

target "201-py39-rocm61-ubuntu2004" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.0.1-py3.9-rocm6.1-ubuntu20.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm6.1_ubuntu20.04_py3.9_pytorch_2.0.1"
    }
}

target "212-py310-rocm61-ubuntu2204" {
    dockerfile = "Dockerfile"
    tags = ["${PUBLISHER}/pytorch:2.1.2-py3.10-rocm6.1-ubuntu22.04"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
        logo = "../../container-template"
    }
    args = {
        BASE_IMAGE = "rocm/pytorch:rocm6.1_ubuntu22.04_py3.10_pytorch_2.1.2"
    }
}


