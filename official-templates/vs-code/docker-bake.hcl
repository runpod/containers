variable "RELEASE" {
  default = "0.1.0"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/vs-code"
  dockerfile = "Dockerfile"
  tags = ["runpod/coder:${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
