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
    BASE_IMAGE = "ubuntu:26.04@sha256:6a06111c3b0a8600feadb270aec771dc239bf407b25625f93f44ab00e11f4d3c"
  }

  tags = [
    "runpod/ubuntu:${RELEASE_VERSION}${RELEASE_SUFFIX}-sandbox-ubuntu2604",
  ]
}
