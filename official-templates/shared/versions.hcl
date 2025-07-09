RELEASE_VERSION = "0.7.0"

UBUNTU_VERSIONS = [
  {
    version = "20.04"
    name = "ubuntu2004"
    alias = "focal"
  },
  {
    version = "22.04"
    name = "ubuntu2204"
    alias = "jammy"
  },
  {
    version = "24.04"
    name = "ubuntu2404"
    alias = "noble"
  }
]

CUDA_VERSIONS = [
  {
    version = "12.4.1"
    ubuntu = ["20.04", "22.04"]
  },
  {
    version = "12.5.1"
    ubuntu = ["20.04", "22.04"]
  },
  {
    version = "12.6.3"
    ubuntu = ["20.04", "22.04", "24.04"]
  },
  {
    version = "12.8.1"
    ubuntu = ["20.04", "22.04", "24.04"]
  },
  {
    version = "12.9.0"
    ubuntu = ["20.04", "22.04", "24.04"]
  }
]

