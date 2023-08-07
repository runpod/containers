target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:1.13.0-py3.10-cuda11.7.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        TORCH = "torch==1.13.1+cu117 torchvision==0.14.1+cu117 torchaudio==0.13.1 --extra-index-url https://download.pytorch.org/whl/cu117"
    }
}

target "1-py38-cuda1162-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:1.13.1-py3.8-cuda11.6.2-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.6.2-devel-ubuntu20.04"
        TORCH_URL = "https://download.pytorch.org/whl/cu116"
    }
}

target "201-py310-cuda1171-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:2.0.1-py3.10-cuda11.7.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.7.1-devel-ubuntu22.04"
        TORCH_URL = "https://download.pytorch.org/whl/cu117"
    }
}

target "201-py310-cuda1180-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:11.8.0-devel-ubuntu22.04"
        TORCH = "torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118"
    }
}

target "200nightly-py310-cuda1201-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:2.0.0.nightly-py3.10-cuda12.0.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
    args = {
        BASE_IMAGE = "nvidia/cuda:12.0.1-devel-ubuntu22.04"
        TORCH_URL = "https://download.pytorch.org/whl/nightly/cu121"
    }
}

target "191-py310-cuda111-devel" {
    dockerfile = "Dockerfile"
    tags = ["runpod/pytorch:1.9.1-py3.10-cuda11.1.1-devel"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }  
    args = {
        BASE_IMAGE = "nvidia/cuda:11.1.1-cudnn8-devel-ubuntu20.04"
        TORCH = "torch==1.9.1+cu111 torchvision==0.10.1+cu111 torchaudio==0.9.1 -f https://download.pytorch.org/whl/torch_stable.html"
    }
}