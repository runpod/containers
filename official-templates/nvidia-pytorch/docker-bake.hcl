variable "TORCH_COMBINATIONS" {
  default = [
    { pytorch = "25.11" }
  ]
}

group "pytorch2511" {
  targets = [
    for build in TORCH_COMBINATIONS:
      "pytorch-${replace(build.pytorch, ".", "")}"
      if build.pytorch == "25.11"
  ]
}

target "nvidia-base" {
  inherits = ["_oci-labels"]
  context = "official-templates/base"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
    requirements = "official-templates/nvidia-pytorch"
    scrub_stale_metadata = "scripts"
  }
  args = {
    RP_SKIP_PYTHON = "1"
  }
  labels = {
    "org.opencontainers.image.title"       = "Runpod NVIDIA PyTorch"
    "org.opencontainers.image.description" = "Runpod image built on NVIDIA's NGC PyTorch container with the Runpod base tooling layered on top."
  }
}

target "pytorch-matrix" {
  matrix = {
    build = TORCH_COMBINATIONS
  }
  
  name = "pytorch-${replace(build.pytorch, ".", "")}"
  
  inherits = ["nvidia-base"]

  tags = [
    "runpod/nvidia-pytorch:${RELEASE_VERSION}${RELEASE_SUFFIX}-${build.pytorch}",
  ]

  args = {
    BASE_IMAGE = "nvcr.io/nvidia/pytorch:${build.pytorch}-py3"
  }
}
