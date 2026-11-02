# Curated sandbox images. CPU only — sandboxes run under gVisor without GPUs
# for the MVP, so there is no CUDA matrix here.

group "default" {
  targets = ["sandbox-ubuntu"]
}

target "sandbox-ubuntu" {
  context    = "official-templates/sandbox-ubuntu"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  args = {
    # Digest-pinned: the warm pool is keyed on the image, and `ubuntu:26.04`
    # is rebuilt upstream every few weeks.
    BASE_IMAGE = "ubuntu:26.04@sha256:cd21a4f68a617580279d4b091cb18e3af9fa8a87500665f0ae5f7f757d17d367"
  }

  tags = [
    "runpod/ubuntu:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-ubuntu2604",
  ]
}
