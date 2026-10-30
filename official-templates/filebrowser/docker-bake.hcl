# FileBrowser template
# Builds on runpod/base, Ubuntu 24.04 only: a CPU image (FileBrowser does not
# use the GPU) plus one CUDA image for pods that want GPU tooling alongside the
# file browser. Each FileBrowser release is built for both variants and tagged
# with its version, so multiple versions ship side by side. Adding a version is
# one line in FILEBROWSER_VERSIONS; the CUDA variant is set by FILEBROWSER_CUDA.

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

# The single CUDA version shipped alongside the CPU image. Must be a 24.04 CUDA
# build that runpod/base publishes (see shared/versions.hcl).
variable "FILEBROWSER_CUDA" {
  default = "12.8.1"
}

variable "FILEBROWSER_BUILDS" {
  default = flatten([
    for fb in FILEBROWSER_VERSIONS : [
      for variant in [
        # CPU: runpod/base:<ver>-ubuntu2404, the common case.
        { name = "cpu", base_suffix = "ubuntu2404" },
        # One CUDA image: runpod/base:<ver>-cuda<code>-ubuntu2404.
        {
          name        = "cuda${replace(FILEBROWSER_CUDA, ".", "")}"
          base_suffix = "cuda${replace(FILEBROWSER_CUDA, ".", "")}-ubuntu2404"
        },
      ] : {
        filebrowser_version = fb.version
        # v2.0.1-stable -> 201stable, for target and group names
        filebrowser_version_code = replace(replace(replace(fb.version, "v", ""), ".", ""), "-", "")
        filebrowser_sha256       = fb.sha256
        variant_name             = variant.name
        base_suffix              = variant.base_suffix
      }
    ]
  ])
}

# Groups are how CI shards the build: `cpu` for the CPU image, `cuda` for the
# single CUDA image. Both names stay stable regardless of FILEBROWSER_CUDA, so
# base.yml never changes when the CUDA version does.
group "default" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-${build.variant_name}"
  ]
}

group "cpu" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-${build.variant_name}"
    if build.variant_name == "cpu"
  ]
}

group "cuda" {
  targets = [
    for build in FILEBROWSER_BUILDS :
    "filebrowser${build.filebrowser_version_code}-${build.variant_name}"
    if build.variant_name != "cpu"
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

  name = "filebrowser${build.filebrowser_version_code}-${build.variant_name}"

  args = {
    BASE_IMAGE          = "runpod/base:${BASE_VERSION}-${build.base_suffix}"
    FILEBROWSER_VERSION = build.filebrowser_version
    FILEBROWSER_SHA256  = build.filebrowser_sha256
  }

  tags = [
    "runpod/filebrowser:${RELEASE_VERSION}${RELEASE_SUFFIX}-filebrowser${build.filebrowser_version}-${build.base_suffix}",
  ]
}
