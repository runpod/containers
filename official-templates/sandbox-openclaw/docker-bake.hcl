# OpenClaw sandbox image, layered on the upstream release.
#
# Upstream also publishes `-browser` variants with Chromium baked in. We do
# not build them: a baked browser cannot be kept patched (theirs currently
# trails the fixed release by two major versions, with actively exploited
# CVEs), and its only benefit is skipping a one-off install at first use.

variable "OPENCLAW_VERSION" {
  default = "2026.11.6"
}

variable "OPENCLAW_DIGEST" {
  # Pinned alongside the version so the tag we publish and the bits we build
  # on can never drift apart.
  default = "sha256:65e229536a2698f0ab211c8a3d1c5c8e2685d19379d153e95f93ff76f22779cf"
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
    "runpod/openclaw${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-${OPENCLAW_VERSION}",
  ]
}
