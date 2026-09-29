# Autoresearch template
# Builds on runpod/base. 24.04 gets every CUDA version the base image offers
# for it; 22.04 keeps the 12.8.1 build it already had and is not widened —
# Ubuntu 22.04 is on its way out.

variable "AUTORESEARCH_BUILDS" {
  default = flatten([
    for cuda in CUDA_VERSIONS : [
      for ubuntu in UBUNTU_VERSIONS : {
        ubuntu_name = ubuntu.name
        cuda_code   = replace(cuda.version, ".", "")
      } if contains(cuda.ubuntu, ubuntu.version)
        && (ubuntu.version == "24.04" || cuda.version == "12.8.1")
    ]
  ])
}

group "default" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"
  ]
}

group "cuda1281" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1281"
  ]
}

group "cuda1290" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1290"
  ]
}

group "cuda1300" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1300"
  ]
}

group "cuda1320" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1320"
  ]
}

target "autoresearch-base" {
  context    = "official-templates/autoresearch"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "autoresearch-matrix" {
  inherits = ["autoresearch-base"]

  matrix = {
    build = AUTORESEARCH_BUILDS
  }

  name = "autoresearch-${build.ubuntu_name}-cuda${build.cuda_code}"

  args = {
    BASE_IMAGE = "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${build.cuda_code}-${build.ubuntu_name}"
  }

  tags = [
    "runpod/autoresearch:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${build.cuda_code}-${build.ubuntu_name}",
  ]
}
