# Harbor sandbox image, layered on our own sandbox-ubuntu so the user, init
# and Python toolchain stay identical across the sandbox family.

variable "HARBOR_VERSION" {
  default = "0.23.0"
}

group "default" {
  targets = ["sandbox-harbor"]
}

target "sandbox-harbor" {
  context    = "official-templates/sandbox-harbor"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  args = {
    BASE_IMAGE     = "runpod/ubuntu:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-ubuntu2604"
    HARBOR_VERSION = HARBOR_VERSION
  }

  tags = [
    "runpod/harbor:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-${HARBOR_VERSION}",
  ]
}
