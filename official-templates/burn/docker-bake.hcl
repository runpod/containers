# Burn template
# Builds on runpod/base: one image per CUDA/Ubuntu combo the CUDA base offers
# (shared/versions.hcl).

# Which published runpod/base to build FROM — in-run base tag when base was
# rebuilt in this run, else the last released base (see base.yml).
variable "BASE_VERSION" {
  default = "2.1.0"
}

# Burn release the starter project pins (Cargo.toml).
variable "BURN_VERSION" {
  default = "0.22.1"
}

variable "BURN_BUILDS" {
  default = flatten([
    for cuda in CUDA_VERSIONS : [
      for ubuntu in UBUNTU_VERSIONS : {
        ubuntu_name = ubuntu.name
        cuda_code   = replace(cuda.version, ".", "")
      } if contains(cuda.ubuntu, ubuntu.version)
    ]
  ])
}

group "default" {
  targets = [
    for build in BURN_BUILDS :
    "burn-${build.ubuntu_name}-cuda${build.cuda_code}"
  ]
}

group "cuda1281" {
  targets = [
    for build in BURN_BUILDS :
    "burn-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1281"
  ]
}

group "cuda1290" {
  targets = [
    for build in BURN_BUILDS :
    "burn-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1290"
  ]
}

group "cuda1300" {
  targets = [
    for build in BURN_BUILDS :
    "burn-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1300"
  ]
}

group "cuda1320" {
  targets = [
    for build in BURN_BUILDS :
    "burn-${build.ubuntu_name}-cuda${build.cuda_code}"
    if build.cuda_code == "1320"
  ]
}

target "burn-base" {
  context    = "official-templates/burn"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "burn-matrix" {
  inherits = ["burn-base"]

  matrix = {
    build = BURN_BUILDS
  }

  name = "burn-${build.ubuntu_name}-cuda${build.cuda_code}"

  args = {
    BASE_IMAGE = "runpod/base:${BASE_VERSION}-cuda${build.cuda_code}-${build.ubuntu_name}"
    BURN_VERSION = BURN_VERSION
  }

  tags = [
    "runpod/burn:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${build.cuda_code}-${build.ubuntu_name}",
  ]
}
