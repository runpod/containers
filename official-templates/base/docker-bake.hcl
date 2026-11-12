group "cpu" {
  targets = ["cpu-ubuntu2404", "cpu-ubuntu2604"]
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
    requirements = "official-templates/base"
    scrub_stale_metadata = "scripts"
  }
}

target "cpu-ubuntu2404" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-ubuntu2404",
  ]
  args = {
    BASE_IMAGE = "ubuntu:24.04"
    UBUNTU_VERSION = "24.04"
  }
}

target "cpu-ubuntu2604" {
  inherits = ["common-base"]
  tags = [
    "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-ubuntu2604",
  ]
  args = {
    BASE_IMAGE = "ubuntu:26.04"
    UBUNTU_VERSION = "26.04"
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
    "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${combo.cuda_code}-${combo.ubuntu_name}",
  ]
  
  # -cudnn-runtime plus the devel image's dev packages (the cuda-dev stage), not
  # -cudnn-devel: same toolchain without the static libraries and Nsight
  # Compute. See the cuda-dev stage in the Dockerfile.
  args = {
    BASE_IMAGE = "nvidia/cuda:${combo.cuda_version}-cudnn-runtime-ubuntu${combo.ubuntu_version}"
    ROOT_STAGE = "cuda-dev"
    UBUNTU_VERSION = combo.ubuntu_version
  }
}
