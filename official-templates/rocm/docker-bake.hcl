variable "ROCM_TORCH_COMBINATIONS" {
  default = [
    { rocm = "6.4.4", ubuntu = "22.04", python = "3.10", torch = "2.6.0" },
    { rocm = "6.4.4", ubuntu = "24.04", python = "3.12", torch = "2.6.0" },
    { rocm = "6.4.4", ubuntu = "24.04", python = "3.12", torch = "2.7.1" },
    # ROCm 7.x is required for gfx950 (Instinct MI350X/MI355X); 6.x runtimes
    # have no gfx950 code objects and rocminfo lists no GPU agent on those hosts.
    { rocm = "7.2.4", ubuntu = "24.04", python = "3.12", torch = "2.10.0" },
  ]
}

group "rocm644" {
  targets = [
    for build in ROCM_TORCH_COMBINATIONS:
      "rocm${replace(build.rocm, ".", "")}-ubuntu${replace(build.ubuntu, ".", "")}-py${replace(build.python, ".", "")}-pytorch${replace(build.torch, ".", "")}"
      if build.rocm == "6.4.4"
  ]
}

group "rocm724" {
  targets = [
    for build in ROCM_TORCH_COMBINATIONS:
      "rocm${replace(build.rocm, ".", "")}-ubuntu${replace(build.ubuntu, ".", "")}-py${replace(build.python, ".", "")}-pytorch${replace(build.torch, ".", "")}"
      if build.rocm == "7.2.4"
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
  
  name = "rocm${replace(build.rocm, ".", "")}-ubuntu${replace(build.ubuntu, ".", "")}-py${replace(build.python, ".", "")}-pytorch${replace(build.torch, ".", "")}"
  
  inherits = ["rocm-base"]

  args = {
    BASE_IMAGE = "rocm/pytorch:rocm${build.rocm}_ubuntu${build.ubuntu}_py${build.python}_pytorch_release_${build.torch}"
  }

  tags = [
    "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-rocm${replace(build.rocm, ".", "")}-ubuntu${replace(build.ubuntu, ".", "")}-py${replace(build.python, ".", "")}-pytorch${replace(build.torch, ".", "")}",
  ]
}
