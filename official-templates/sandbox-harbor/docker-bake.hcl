# Harbor sandbox image, layered on our own sandbox-ubuntu so the user, init
# and Python toolchain stay identical across the sandbox family.

variable "HARBOR_VERSION" {
  default = "0.23.0"
}

# Which published runpod/ubuntu to build FROM — in-run sandbox-ubuntu tag when
# it was rebuilt in this run, else the last released one (see sandbox.yml).
variable "UBUNTU_BASE_VERSION" {
  default = "1.0.7"
}

# Repo suffix of that runpod/ubuntu: "-dev" when CI built it in this run on
# the dev env (runpod/ubuntu-dev), else empty — a published one is
# public.
variable "UBUNTU_BASE_REPO_SUFFIX" {
  default = ""
}

group "default" {
  targets = ["sandbox-harbor"]
}

target "sandbox-harbor" {
  context    = "official-templates/sandbox-harbor"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  args = {
    BASE_IMAGE     = "runpod/ubuntu${UBUNTU_BASE_REPO_SUFFIX}:${UBUNTU_BASE_VERSION}-sandbox-ubuntu2604"
    HARBOR_VERSION = HARBOR_VERSION
  }

  tags = [
    "runpod/harbor${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-${HARBOR_VERSION}",
  ]
}
