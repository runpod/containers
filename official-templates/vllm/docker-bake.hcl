# Bump VLLM_VERSION and VLLM_DIGEST together; the digest is the index digest
# from `docker buildx imagetools inspect vllm/vllm-openai:<version>`.

variable "VLLM_VERSION" {
  default = "v0.34.0"
}

variable "VLLM_DIGEST" {
  default = "sha256:20fdb089454afbb324efa4110a2c025ff7b27cc1a086e07aa580b18df8ad1ce1"
}

group "default" {
  targets = ["vllm"]
}

target "vllm" {
  context    = "official-templates/vllm"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]

  args = {
    VLLM_IMAGE = "vllm/vllm-openai:${VLLM_VERSION}@${VLLM_DIGEST}"
  }

  tags = [
    "runpod/vllm-openai${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-vllm${VLLM_VERSION}"
  ]
}
