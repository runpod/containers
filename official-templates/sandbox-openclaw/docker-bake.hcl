# OpenClaw sandbox image, layered on the upstream release.
#
# Upstream also publishes `-browser` variants with Chromium baked in. We do
# not build them: a baked browser cannot be kept patched (theirs currently
# trails the fixed release by two major versions, with actively exploited
# CVEs), and its only benefit is skipping a one-off install at first use.

variable "OPENCLAW_VERSION" {
  default = "2026.9.4"
}

variable "OPENCLAW_DIGEST" {
  # Pinned alongside the version so the tag we publish and the bits we build
  # on can never drift apart.
  default = "sha256:cc596b846506a5f4cfcee111394a2725f375f01cca2ebb492a161fd1b747f101"
}

group "default" {
  targets = ["sandbox-openclaw"]
}

target "sandbox-openclaw" {
  context    = "official-templates/sandbox-openclaw"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  args = {
    BASE_IMAGE = "ghcr.io/openclaw/openclaw:${OPENCLAW_VERSION}@${OPENCLAW_DIGEST}"
  }

  tags = [
    "runpod/openclaw:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-${OPENCLAW_VERSION}",
  ]
}
