variable "RELEASE_VERSION" {
  # Fallback for local `docker buildx bake` runs. In CI this is overridden
  # from the latest git tag + Conventional Commits (see compute-version action).
  default = "1.0.7"
}

variable "RELEASE_SUFFIX" {
  default = "" # Set by CI, not used by humans.
}

UBUNTU_VERSIONS = [
  {
    version = "22.04"
    name = "ubuntu2204"
  },
  {
    version = "24.04"
    name = "ubuntu2404"
  }
]

CUDA_VERSIONS = [
  {
    version = "12.8.1"
    ubuntu = ["22.04", "24.04"]
  },
  {
    version = "12.9.0"
    ubuntu = ["22.04", "24.04"]
  },
  {
    version = "13.0.0"
    ubuntu = ["24.04"]
  }
]
