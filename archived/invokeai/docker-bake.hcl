variable "RELEASE" {
  default = "3.3.0"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/invokeai"
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:invoke-${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
