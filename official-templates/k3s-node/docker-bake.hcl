# k3s agent image for Runpod K8S cluster pods. amd64 and arm64 (GB10/Grace hosts), in one
# multi-platform image.

variable "K3S_VERSION" {
  default = "v1.37.1+k3s1"
}

# Remove with the runc swap in k3s-node.sh once k3s bundles runc >= 1.4.3.
variable "RUNC_VERSION" {
  default = "v1.4.3"
}

# The apt package version of nvidia-container-toolkit and its libraries.
variable "NVIDIA_CTK_VERSION" {
  default = "1.20.1-1"
}

group "default" {
  targets = ["k3s-node"]
}

target "k3s-node" {
  context    = "official-templates/k3s-node"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]

  args = {
    # Digest-pinned, so a rebuild without a change here yields the same OS layer.
    BASE_IMAGE = "ubuntu:24.04@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c"

    K3S_VERSION      = K3S_VERSION
    K3S_SHA256_AMD64 = "92b94582eb7b34a8cf532e6006842b9ed215a6783cf56a3dd6271fd35243b2c0"
    K3S_SHA256_ARM64 = "a1561ca4aef8b99f5588a840d4468ac39c8c1cd92470bbcb9634823fa221741a"

    RUNC_VERSION      = RUNC_VERSION
    RUNC_SHA256_AMD64 = "f6ae8efc0fa40079e1475e97cbe9d1bd3f106a28d6af78a11d9f1bd565515e60"
    RUNC_SHA256_ARM64 = "633301e2e32f8a5ad54031aab4901eb00308bec677dd15faa2751e8f9dab5ca4"

    NVIDIA_CTK_VERSION = NVIDIA_CTK_VERSION
  }

  # The k3s version without its build suffix: v1.37.1+k3s1 -> k3s-v1.37.1.
  tags = [
    "runpod/k3s-node:${RELEASE_VERSION}${RELEASE_SUFFIX}-k3s-${split("+", K3S_VERSION)[0]}",
  ]
}
