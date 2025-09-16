group "cpu" {
  targets = ["cpu-ubuntu2204", "cpu-ubuntu2404"]
}

group "default" {
  targets = ["cpu", "cuda-matrix"]
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

target "cpu-ubuntu2204" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-ubuntu2204",
  ]
  args = {
    BASE_IMAGE = "ubuntu:22.04"
  }
}

target "cpu-ubuntu2404" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}-ubuntu2404",
  ]
  args = {
    BASE_IMAGE = "ubuntu:24.04"
  }
}

target "cuda-matrix" {
  inherits = ["common-base"]
  
  name = "cuda-${combo.ubuntu_name}-${replace(combo.cuda_version, ".", "")}"
  
  matrix = {
    combo = flatten([
      for cuda in CUDA_VERSIONS: [
        for ubuntu in UBUNTU_VERSIONS: {
          ubuntu_version = ubuntu.version
          ubuntu_name = ubuntu.name
          cuda_code = replace(cuda.version, ".", "")
          cuda_version = cuda.version
        } if contains(cuda.ubuntu, ubuntu.version)
      ]
    ])
  }
  
  tags = [
    "runpod/base:${RELEASE_VERSION}-cuda${combo.cuda_code}-${combo.ubuntu_name}",
  ]
  
  args = {
    BASE_IMAGE = "nvidia/cuda:${combo.cuda_version}-cudnn-devel-ubuntu${combo.ubuntu_version}"
  }
}

# the line we change to make ci run
