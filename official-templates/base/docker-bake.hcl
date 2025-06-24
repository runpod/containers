variable "GITHUB_WORKSPACE" {
  default = "."
}

group "cpu" {
  targets = ["cpu-ubuntu2004", "cpu-ubuntu2204", "cpu-ubuntu2404"]
}

group "cuda" {
  targets = ["cuda-matrix"]
}

group "default" {
  targets = ["cpu", "cuda"]
}

target "common-base" {
  context = "official-templates/base"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
  }
}

target "cpu-ubuntu2004" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}",
    "runpod/base:${RELEASE_VERSION}-ubuntu2004",
  ]
  args = {
    BASE_IMAGE = "ubuntu:20.04"
  }
}

target "cpu-ubuntu2204" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-ubuntu2204",
    "runpod/base:${RELEASE_VERSION}-jammy",
  ]
  args = {
    BASE_IMAGE = "ubuntu:22.04"
  }
}

target "cpu-ubuntu2404" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-ubuntu2404",
    "runpod/base:${RELEASE_VERSION}-noble",
  ]
  args = {
    BASE_IMAGE = "ubuntu:24.04"
  }
}

target "cuda-matrix" {
  inherits = ["common-base"]
  
  name = "cuda-${combo.ubuntu_name}-${combo.cuda_code}"
  
  matrix = {
    combo = flatten([
      for cuda in CUDA_VERSIONS: [
        for ubuntu in UBUNTU_VERSIONS: {
          ubuntu_version = ubuntu.version
          ubuntu_code = ubuntu.code
          ubuntu_name = ubuntu.name
          ubuntu_alias = ubuntu.alias
          cuda_code = cuda.code
          cuda_version = cuda.version
        } if contains(cuda.ubuntu, ubuntu.version)
      ]
    ])
  }
  
  tags = [
    "runpod/base:${RELEASE_VERSION}-cuda${combo.cuda_version}-${combo.ubuntu_name}",
    "runpod/base:${RELEASE_VERSION}-cuda${combo.cuda_version}-${combo.ubuntu_alias}",
    "runpod/base:${RELEASE_VERSION}-${combo.ubuntu_name}-cuda${combo.cuda_version}",
    "runpod/base:${RELEASE_VERSION}-${combo.ubuntu_alias}-cuda${combo.cuda_version}"
  ]
  
  args = {
    BASE_IMAGE = "nvidia/cuda:${combo.cuda_version}-cudnn-runtime-ubuntu${combo.ubuntu_version}"
  }
}
