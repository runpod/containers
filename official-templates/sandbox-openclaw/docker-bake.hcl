# OpenClaw sandbox images, layered on the upstream release. Two variants:
# the plain image, and `-browser` which bundles Chromium so the agent itself
# can drive a browser.

variable "OPENCLAW_VERSION" {
  default = "2026.9.4"
}

# Digests pinned alongside the version so the tag we publish and the bits we
# build on can never drift apart.
variable "OPENCLAW_VARIANTS" {
  default = [
    {
      suffix = ""
      digest = "sha256:cc596b846506a5f4cfcee111394a2725f375f01cca2ebb492a161fd1b747f101"
    },
    {
      suffix = "-browser"
      digest = "sha256:0862ab9a097166049800a6c86026b035b768af0949f651d0e73222555b28fbbd"
    }
  ]
}

group "default" {
  targets = [for v in OPENCLAW_VARIANTS : "sandbox-openclaw${v.suffix}"]
}

target "openclaw-base" {
  context    = "official-templates/sandbox-openclaw"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "openclaw-matrix" {
  inherits = ["openclaw-base"]

  matrix = {
    variant = OPENCLAW_VARIANTS
  }

  name = "sandbox-openclaw${variant.suffix}"

  args = {
    BASE_IMAGE = "ghcr.io/openclaw/openclaw:${OPENCLAW_VERSION}${variant.suffix}@${variant.digest}"
  }

  tags = [
    "runpod/openclaw:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-${OPENCLAW_VERSION}${variant.suffix}",
  ]
}
