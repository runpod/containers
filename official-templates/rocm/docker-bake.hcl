variable "ROCM_TORCH_COMBINATIONS" {
  default = [
    { rocm = "6.4.4", ubuntu = "22.04", python = "3.10", torch = "2.6.0" },
    { rocm = "6.4.4", ubuntu = "24.04", python = "3.12", torch = "2.6.0" },
    { rocm = "6.4.4", ubuntu = "24.04", python = "3.12", torch = "2.7.1" },
  ]
}

group "rocm644" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "rocm${build.rocm}-ubuntu${build.ubuntu}-py${build.python}-pytorch${build.torch}"
      if build.rocm == "6.4.4"
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
    requirements = "official-templates/rocm"
    scrub_stale_metadata = "scripts"
  }
  args = {
    RP_SKIP_PYTHON = "1"
  }
}

target "rocm-matrix" {
  matrix = {
    build = ROCM_TORCH_COMBINATIONS
  }
  
  name = "rocm${build.rocm}-ubuntu${build.ubuntu}-py${build.python}-pytorch${build.torch}"
  
  inherits = ["rocm-base"]

  args = {
    BASE_IMAGE = "rocm/pytorch:rocm${build.rocm}_ubuntu${build.ubuntu}_py${build.python}_pytorch_release_${build.torch}"
  }

  tags = [
    "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-rocm${replace(build.rocm, ".", "")}-ubuntu${replace(build.ubuntu, ".", "")}-py${replace(build.python, ".", "")}-pytorch${replace(build.torch, ".", "")}",
  ]
}

// target "rocm644-ubuntu2204-pytorch260" {
//   inherits = ["rocm-base"]
//   tags = [
//     "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-rocm644-ubuntu2204-py310-pytorch260",
//   ]
//   args = {
//     BASE_IMAGE = "rocm/pytorch:rocm6.4.4_ubuntu22.04_py3.10_pytorch_release_2.6.0"
//   }
// }

// target "rocm644-ubuntu2404-pytorch260" {
//   inherits = ["rocm-base"]
//   tags = [
//     "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-rocm644-ubuntu2404-py312-pytorch260",
//   ]
//   args = {
//     BASE_IMAGE = "rocm/pytorch:rocm6.4.4_ubuntu24.04_py3.12_pytorch_release_2.6.0"
//   }
// }

// target "rocm644-ubuntu2404-pytorch271" {
//   inherits = ["rocm-base"]
//   tags = [
//     "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-rocm644-ubuntu2404-py312-pytorch271",
//   ]
//   args = {
//     BASE_IMAGE = "rocm/pytorch:rocm6.4.4_ubuntu24.04_py3.12_pytorch_release_2.7.1"
//   }
// }
