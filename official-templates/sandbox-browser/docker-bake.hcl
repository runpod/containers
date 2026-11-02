# Browser sandbox image, layered on our own sandbox-ubuntu so the user, init
# and toolchains stay identical across the sandbox family.

# Python and Node Playwright share it; PyPI usually trails npm by a week or
# two, so the newest version published on both is the one to pin.
variable "PLAYWRIGHT_VERSION" {
  default = "1.63.0"
}

# Which published runpod/ubuntu to build FROM — in-run sandbox-ubuntu tag when
# it was rebuilt in this run, else the last released one (see sandbox.yml).
variable "UBUNTU_BASE_VERSION" {
  default = "1.0.0"
}

# Repo suffix of that runpod/ubuntu: "-dev" when CI built it in this run on
# the dev env (runpod/ubuntu-dev), else empty — a published one is public.
variable "UBUNTU_BASE_REPO_SUFFIX" {
  default = ""
}

group "default" {
  targets = ["sandbox-browser"]
}

target "sandbox-browser" {
  inherits   = ["_oci-labels"]
  context    = "official-templates/sandbox-browser"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  labels = {
    "org.opencontainers.image.title"       = "Runpod Sandbox Browser"
    "org.opencontainers.image.description" = "Runpod sandbox browser image: the sandbox Ubuntu base plus Playwright for browser automation."
  }

  args = {
    BASE_IMAGE         = "runpod/ubuntu${UBUNTU_BASE_REPO_SUFFIX}:${UBUNTU_BASE_VERSION}-sandbox-ubuntu2604"
    PLAYWRIGHT_VERSION = PLAYWRIGHT_VERSION
  }

  tags = [
    "runpod/browser${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-playwright${PLAYWRIGHT_VERSION}",
  ]
}
