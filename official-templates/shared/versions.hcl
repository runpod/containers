RELEASE_VERSION = "1.0.9"

variable "RELEASE_SUFFIX" {
  default = "" # Set by CI, not used by humans.
}


variable "GIT_SHA" {
  default = "" # Set by CI to the built commit SHA (github.sha).
}

variable "BUILD_DATE" {
  default = "" # Set by CI to an RFC3339 UTC timestamp (docker-setup build-date).
}

# Shared OCI image labels (https://github.com/opencontainers/image-spec).
# Every family's *-base target inherits this so provenance/metadata stays
# consistent; each family layers its own image.title / image.description on
# top (bake merges the maps). We intentionally omit image.licenses.
target "_oci-labels" {
  labels = {
    "org.opencontainers.image.source"        = "https://github.com/runpod/containers"
    "org.opencontainers.image.url"           = "https://github.com/runpod/containers"
    "org.opencontainers.image.documentation" = "https://github.com/runpod/containers"
    "org.opencontainers.image.vendor"        = "Runpod"
    "org.opencontainers.image.version"       = "${RELEASE_VERSION}${RELEASE_SUFFIX}"
    "org.opencontainers.image.revision"      = "${GIT_SHA}"
    "org.opencontainers.image.created"       = "${BUILD_DATE}"
  }
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
