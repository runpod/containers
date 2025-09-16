RELEASE_VERSION = "1.0.0"

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

