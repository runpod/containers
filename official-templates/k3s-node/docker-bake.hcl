# k3s agent image for Runpod K8S cluster pods. amd64 and arm64 (GB10/Grace hosts), in one
# multi-platform image.

variable "K3S_VERSION" {
  default = "v1.37.2+k3s1"
}

# Remove with the runc swap in k3s-node.sh once k3s bundles runc >= 1.4.3.
variable "RUNC_VERSION" {
  default = "v1.4.3"
}

# The apt package version of nvidia-container-toolkit and its libraries.
variable "NVIDIA_CTK_VERSION" {
  default = "1.20.2-1"
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
    K3S_SHA256_AMD64 = "265b3ee6a3198ef14033c63ef46cbb32370d83795199fb6d1b01f21575eddbda"
    K3S_SHA256_ARM64 = "a779ccf1e5e2e33a62f5a29c2f1c0bbf99431e100579d4c10f0aa0742a6aa84b"

    RUNC_VERSION      = RUNC_VERSION
    RUNC_SHA256_AMD64 = "f6ae8efc0fa40079e1475e97cbe9d1bd3f106a28d6af78a11d9f1bd565515e60"
    RUNC_SHA256_ARM64 = "633301e2e32f8a5ad54031aab4901eb00308bec677dd15faa2751e8f9dab5ca4"

    NVIDIA_CTK_VERSION = NVIDIA_CTK_VERSION
  }

  # The k3s version without its build suffix: v1.37.2+k3s1 -> k3s-v1.37.2.
  tags = [
    "runpod/k3s-node${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-k3s-${split("+", K3S_VERSION)[0]}",
  ]
}
