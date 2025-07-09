group "default" {
  targets = [
    "rocm641-ubuntu2204-pytorch251",
    "rocm641-ubuntu2204-pytorch260",
    "rocm641-ubuntu2404-pytorch260",
    "rocm641-ubuntu2404-pytorch270",
  ]
}

target "rocm-base" {
  context = "official-templates/base"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
  }
}

target "rocm641-ubuntu2204-pytorch251" {
  inherits = ["rocm-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-rocm641-ubuntu2204-py310-pytorch251",
  ]
  args = {
    BASE_IMAGE = "rocm/pytorch:rocm6.4.1_ubuntu22.04_py3.10_pytorch_release_2.5.1"
  }
}

target "rocm641-ubuntu2204-pytorch260" {
  inherits = ["rocm-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-rocm641-ubuntu2204-py310-pytorch260",
  ]
  args = {
    BASE_IMAGE = "rocm/pytorch:rocm6.4.1_ubuntu22.04_py3.10_pytorch_release_2.6.0"
  }
}

target "rocm641-ubuntu2404-pytorch260" {
  inherits = ["rocm-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-rocm641-ubuntu2404-py312-pytorch260",
  ]
  args = {
    BASE_IMAGE = "rocm/pytorch:rocm6.4.1_ubuntu24.04_py3.12_pytorch_release_2.6.0"
  }
}

target "rocm641-ubuntu2404-pytorch270" {
  inherits = ["rocm-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-rocm641-ubuntu2404-py312-pytorch270",
  ]
  args = {
    BASE_IMAGE = "rocm/pytorch:rocm6.4.1_ubuntu24.04_py3.12_pytorch_release_2.7.0"
  }
}