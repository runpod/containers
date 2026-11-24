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
    BASE_IMAGE = "ubuntu:26.04@sha256:d66b366dac61b575bee2aef07e9c26e8070096fbe84a3d4d3eb0da069b5d76db"
  }

  tags = [
    "runpod/ubuntu${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-ubuntu2604",
  ]
}
