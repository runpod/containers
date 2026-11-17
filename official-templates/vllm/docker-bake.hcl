# Bump VLLM_VERSION and VLLM_DIGEST together; the digest is the index digest
# from `docker buildx imagetools inspect vllm/vllm-openai:<version>`.

variable "VLLM_VERSION" {
  default = "v0.33.0"
}

variable "VLLM_DIGEST" {
  default = "sha256:d825baf9ce4b1b6bfc5ecc7b79880c7e6748c65a72d697ce3d47607aafa84c6e"
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
    "runpod/vllm-openai:${RELEASE_VERSION}${RELEASE_SUFFIX}-vllm${VLLM_VERSION}"
  ]
}
