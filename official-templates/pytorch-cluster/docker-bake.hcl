# The `-cluster` variant layers monitoring + RDMA on top of published
# runpod/pytorch images. Each entry below MUST correspond to a runpod/pytorch
# tag produced by official-templates/pytorch/docker-bake.hcl.
#
# This is a curated subset rather than the full pytorch matrix (~25 combos) —
# add entries here as more cluster images are needed.

# The published runpod/pytorch version the cluster layer builds FROM. This is
# INTENTIONALLY separate from RELEASE_VERSION (the cluster's own tag): on a PR
# the cluster's version is the *future* release, whose pytorch isn't published
# yet, so we must build on top of an image that actually exists. CI sets this
# to the in-run pytorch tag when pytorch was (re)built, or the last released
# pytorch otherwise (see base.yml build-cluster). May already include a suffix
# (e.g. 1.1.0-rc.5). Defaults to RELEASE_VERSION's default for local runs.
variable "PYTORCH_BASE_VERSION" {
  default = "1.0.7"
}

variable "CLUSTER_BUILDS" {
  default = [
    { cuda_code = "1281", torch_code = "280", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1281", torch_code = "280", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1281", torch_code = "2121", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1281", torch_code = "2121", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1281", torch_code = "2130", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1281", torch_code = "2130", ubuntu_name = "ubuntu2404" },

    { cuda_code = "1290", torch_code = "280", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1290", torch_code = "2121", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1290", torch_code = "2121", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1290", torch_code = "2130", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1290", torch_code = "2130", ubuntu_name = "ubuntu2404" },

    { cuda_code = "1300", torch_code = "291", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1300", torch_code = "2120", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1300", torch_code = "2121", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1300", torch_code = "2130", ubuntu_name = "ubuntu2404" },
  ]
}

group "default" {
  targets = [
    for b in CLUSTER_BUILDS :
    "cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
  ]
}

# Per-CUDA-major groups so CI can shard the matrix across separate runners
# (mirrors the pytorch template).
group "cu1281" {
  targets = [
    for b in CLUSTER_BUILDS :
    "cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1281"
  ]
}

group "cu1290" {
  targets = [
    for b in CLUSTER_BUILDS :
    "cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1290"
  ]
}

group "cu1300" {
  targets = [
    for b in CLUSTER_BUILDS :
    "cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1300"
  ]
}

target "cluster-base" {
  context    = "official-templates/pytorch-cluster"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "cluster-matrix" {
  matrix = {
    build = CLUSTER_BUILDS
  }

  name = "cluster-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"

  inherits = ["cluster-base"]

  args = {
    # Build FROM whichever published pytorch CI picked (see PYTORCH_BASE_VERSION
    # above): the in-run pytorch tag when pytorch was rebuilt in this run, else
    # the last released pytorch. Kept separate from the cluster's OWN tag below
    # so PR builds don't try to layer onto a not-yet-published pytorch version.
    BASE_IMAGE = "runpod/pytorch:${PYTORCH_BASE_VERSION}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}"
    # CUDA major (first two digits of cuda_code) selects the concrete DCGM
    # provider package: cu1281/cu1290 -> cuda12, cu1300 -> cuda13.
    DCGM_PACKAGE = "datacenter-gpu-manager-4-cuda${substr(build.cuda_code, 0, 2)}"
  }

  # The cluster image's OWN tag keeps RELEASE_SUFFIX so dev/PR builds don't
  # clobber the released -cluster tag.
  tags = [
    "runpod/pytorch:${RELEASE_VERSION}${RELEASE_SUFFIX}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}-cluster",
  ]
}
