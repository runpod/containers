# Autoresearch template
# Builds on runpod/base with CUDA 12.8.1 (matches torch cu128 wheels)

variable "AUTORESEARCH_BUILDS" {
  default = flatten([
    for ubuntu in UBUNTU_VERSIONS : {
      ubuntu_version = ubuntu.version
      ubuntu_name    = ubuntu.name
    }
  ])
}

group "default" {
  targets = [
    for build in AUTORESEARCH_BUILDS :
    "autoresearch-${build.ubuntu_name}"
  ]
}

target "autoresearch-base" {
  inherits   = ["_oci-labels"]
  context    = "official-templates/autoresearch"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
  labels = {
    "org.opencontainers.image.title"       = "Runpod Autoresearch"
    "org.opencontainers.image.description" = "Runpod autoresearch image built on runpod/base with CUDA 12.8.1."
  }
}

target "autoresearch-matrix" {
  inherits = ["autoresearch-base"]

  matrix = {
    build = AUTORESEARCH_BUILDS
  }

  name = "autoresearch-${build.ubuntu_name}"

  args = {
    BASE_IMAGE = "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda1281-${build.ubuntu_name}"
  }

  tags = [
    "runpod/autoresearch:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda1281-${build.ubuntu_name}",
  ]
}
