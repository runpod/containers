# FileBrowser template
# Builds on runpod/base CUDA images, Ubuntu 24.04 only. Each FileBrowser release
# is built for every CUDA variant and tagged with its version, so multiple
# versions ship side by side. Adding a version is one line in
# FILEBROWSER_VERSIONS — no CI or group change needed.

# Which published runpod/base to build FROM — in-run base tag when base was
# rebuilt in this run, else the last released base (see base.yml).
variable "BASE_VERSION" {
  default = "1.0.7"
}

# One entry per FileBrowser Quantum release (gtsteffaniak/filebrowser). version
# is the GitHub release tag; sha256 is its linux-amd64 binary checksum.
variable "FILEBROWSER_VERSIONS" {
  default = [
    { version = "v2.0.1-stable", sha256 = "42df10b6f2fcd4db17a53f64a9449e677a528164002fd13b050d348d7c477517" }
  ]
}

variable "FILEBROWSER_BUILDS" {
  default = flatten([
    for fb in FILEBROWSER_VERSIONS : [
      for cuda in CUDA_VERSIONS : [
        for ubuntu in UBUNTU_VERSIONS : {
          filebrowser_version = fb.version
          # v2.0.1-stable -> 201stable, for target and group names
          filebrowser_version_code = replace(replace(replace(fb.version, "v", ""), ".", ""), "-", "")
          filebrowser_sha256       = fb.sha256
          ubuntu_name              = ubuntu.name
          cuda_code                = replace(cuda.version, ".", "")
        } if contains(cuda.ubuntu, ubuntu.version) && ubuntu.version == "24.04"
      ]
    ]
  ])
}

# One group per CUDA variant — how CI shards the build. No per-release group:
# adding a version stays one line in FILEBROWSER_VERSIONS.
group "default" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"
  ]
}

group "cuda1281" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"
    if build.cuda_code == "1281"
  ]
}

group "cuda1290" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"
    if build.cuda_code == "1290"
  ]
}

group "cuda1300" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"
    if build.cuda_code == "1300"
  ]
}

group "cuda1320" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"
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

  name = "filebrowser${build.filebrowser_version_code}-cuda${build.cuda_code}"

  args = {
    BASE_IMAGE          = "runpod/base:${BASE_VERSION}-cuda${build.cuda_code}-${build.ubuntu_name}"
    FILEBROWSER_VERSION = build.filebrowser_version
    FILEBROWSER_SHA256  = build.filebrowser_sha256
  }

  tags = [
    "runpod/filebrowser:${RELEASE_VERSION}${RELEASE_SUFFIX}-filebrowser${build.filebrowser_version}-cuda${build.cuda_code}-${build.ubuntu_name}",
  ]
}
