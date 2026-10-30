variable "RELEASE_VERSION" {
  # Fallback for local `docker buildx bake` runs. In CI this is overridden
  # from the latest git tag + Conventional Commits (see compute-version action).
  default = "1.0.7"
}

variable "RELEASE_SUFFIX" {
  default = "" # Set by CI, not used by humans.
}

# CUDA bases only. nvidia/cuda publishes ubuntu26.04 images from CUDA 13.3
# on, so none of the versions below has one; add 26.04 here (and to the
# matching ubuntu lists) together with a CUDA version that ships it. The CPU
# base targets 26.04 already exist (base/docker-bake.hcl).
UBUNTU_VERSIONS = [
  {
    version = "24.04"
    name = "ubuntu2404"
  }
]

CUDA_VERSIONS = [
  {
    version = "12.8.1"
    ubuntu = ["24.04"]
  },
  {
    version = "12.9.0"
    ubuntu = ["24.04"]
  },
  {
    version = "13.0.0"
    ubuntu = ["24.04"]
  },
  {
    version = "13.2.0"
    ubuntu = ["24.04"]
  }
]
