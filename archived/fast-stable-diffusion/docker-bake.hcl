variable "RELEASE" {
  default = "2.4.0"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/fast-stable-diffusion"
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:fast-stable-diffusion-${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
