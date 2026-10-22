# The ray-cluster image layers Ray onto the published runpod/pytorch-cluster
# images (which already carry RDMA + the DCGM/Prometheus/Grafana monitoring
# stack). Each entry below MUST correspond to a runpod/pytorch-cluster tag
# produced by official-templates/pytorch-cluster/docker-bake.hcl.
#
# Curated subset, like pytorch-cluster — add entries as more Ray images are
# needed. RELEASE_VERSION / RELEASE_SUFFIX come from official-templates/shared/
# versions.hcl (pass it with -f, as bake.sh does).

# The published runpod/pytorch-cluster version this Ray layer builds FROM.
# INTENTIONALLY separate from RELEASE_VERSION (the Ray image's own tag): the two
# families have their own version series, and on a PR the cluster base may not
# be published at the Ray image's version, so we build on top of a cluster image
# that actually exists. CI sets this to the in-run cluster tag when
# pytorch-cluster is part of the build, or its last released version otherwise
# (see base.yml build-ray-cluster). The default is a released pytorch-cluster
# version for local runs; bump it when a newer cluster release is published.
variable "CLUSTER_BASE_VERSION" {
  default = "1.4.1"
}

variable "RAY_VERSION" {
  # Ray >= 2.53 for the unified /api/healthz agent endpoint the local probe
  # relies on (pkg/rayready polls the dashboard's /api/gcs_healthz). Keep in
  # sync with the Dockerfile's RAY_VERSION default.
  default = "2.53.0"
}

variable "RAY_CLUSTER_BUILDS" {
  default = [
    { cuda_code = "1281", torch_code = "280", ubuntu_name = "ubuntu2204" },
    { cuda_code = "1281", torch_code = "280", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1281", torch_code = "2130", ubuntu_name = "ubuntu2404" },

    { cuda_code = "1290", torch_code = "280", ubuntu_name = "ubuntu2404" },
    { cuda_code = "1290", torch_code = "2130", ubuntu_name = "ubuntu2404" },

    { cuda_code = "1300", torch_code = "2130", ubuntu_name = "ubuntu2404" },
  ]
}

group "default" {
  targets = [
    for b in RAY_CLUSTER_BUILDS :
    "ray-cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
  ]
}

# Per-CUDA-major groups so CI can shard the matrix across separate runners
# (mirrors pytorch-cluster).
group "cu1281" {
  targets = [
    for b in RAY_CLUSTER_BUILDS :
    "ray-cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1281"
  ]
}

group "cu1290" {
  targets = [
    for b in RAY_CLUSTER_BUILDS :
    "ray-cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1290"
  ]
}

group "cu1300" {
  targets = [
    for b in RAY_CLUSTER_BUILDS :
    "ray-cluster-${b.ubuntu_name}-cu${b.cuda_code}-torch${b.torch_code}"
    if b.cuda_code == "1300"
  ]
}

target "ray-cluster-base" {
  context    = "official-templates/ray-cluster"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "ray-cluster-matrix" {
  matrix = {
    build = RAY_CLUSTER_BUILDS
  }

  name = "ray-cluster-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"

  inherits = ["ray-cluster-base"]

  args = {
    # Build FROM the published runpod/pytorch-cluster image CI picked (see
    # CLUSTER_BASE_VERSION): the in-run cluster tag when pytorch-cluster was
    # rebuilt in this run, else the last released one.
    BASE_IMAGE   = "runpod/pytorch-cluster:${CLUSTER_BASE_VERSION}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}"
    RAY_VERSION  = "${RAY_VERSION}"
  }

  # The Ray image's OWN tag keeps RELEASE_SUFFIX so dev/PR builds don't clobber
  # the released tag. Published under runpod/ray-cluster.
  tags = [
    "runpod/ray-cluster:${RELEASE_VERSION}${RELEASE_SUFFIX}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}",
  ]
}
