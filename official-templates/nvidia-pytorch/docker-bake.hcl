group "default" {
  targets = ["pytorch-2511"]
}

target "nvidia-base" {
  context = "official-templates/base"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
  }
  args = {
    RP_SKIP_PYTHON  = "1"
    RP_SKIP_JUPYTER = "1"
  }
}

target "pytorch-2511" {
  inherits = ["nvidia-base"]
  tags = [
    "runpod/nvidia-pytorch:${RELEASE_VERSION}${RELEASE_SUFFIX}-25.11",
  ]
  args = {
    BASE_IMAGE = "nvcr.io/nvidia/pytorch:25.11-py3"
  }
}
