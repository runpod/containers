group "default" {
  targets = [
    "nvidia-pytorch-2510-py3",
  ]
}

target "nvidia-pytorch-base" {
  context = "official-templates/nvidia-pytorch"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
  }
}

target "nvidia-pytorch-2510-py3" {
  inherits = ["nvidia-pytorch-base"]
  tags = [
    "ghcr.io/sbhavani/nvidia-pytorch:${RELEASE_VERSION}${RELEASE_SUFFIX}-pytorch2510-py3",
    "ghcr.io/sbhavani/nvidia-pytorch:latest",
  ]
  args = {
    BASE_IMAGE = "nvcr.io/nvidia/pytorch:25.10-py3"
  }
}
