# FileBrowser template
# Builds on runpod/base CUDA images, Ubuntu 24.04 only. 24.04 gets every CUDA
# version the base image offers for it.

# Which published runpod/base to build FROM — in-run base tag when base was
# rebuilt in this run, else the last released base (see base.yml).
variable "BASE_VERSION" {
  default = "1.0.7"
}

# Pinned FileBrowser Quantum release (gtsteffaniak/filebrowser) and its
# linux-amd64 binary checksum.
variable "FILEBROWSER_VERSION" {
  default = "v2.0.1-stable"
}

variable "FILEBROWSER_SHA256" {
  default = "42df10b6f2fcd4db17a53f64a9449e677a528164002fd13b050d348d7c477517"
}

variable "FILEBROWSER_BUILDS" {
  default = flatten([
    for cuda in CUDA_VERSIONS : [
      for ubuntu in UBUNTU_VERSIONS : {
        ubuntu_name = ubuntu.name
        cuda_code   = replace(cuda.version, ".", "")
      } if contains(cuda.ubuntu, ubuntu.version) && ubuntu.version == "24.04"
    ]
  ])
}

group "default" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"
  ]
}

group "cuda1281" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1281"
  ]
}

group "cuda1290" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1290"
  ]
}

group "cuda1300" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1300"
  ]
}

group "cuda1320" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1320"
  ]
}

target "filebrowser-base" {
  context    = "official-templates/filebrowser"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "filebrowser-matrix" {
  inherits = ["filebrowser-base"]

  matrix = {
    build = FILEBROWSER_BUILDS
  }

  name = "filebrowser-${build.ubuntu_name}-cuda${build.cuda_code}"

  args = {
    BASE_IMAGE          = "runpod/base:${BASE_VERSION}-cuda${build.cuda_code}-${build.ubuntu_name}"
    FILEBROWSER_VERSION = FILEBROWSER_VERSION
    FILEBROWSER_SHA256  = FILEBROWSER_SHA256
  }

  tags = [
    "runpod/filebrowser:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${build.cuda_code}-${build.ubuntu_name}",
  ]
}
