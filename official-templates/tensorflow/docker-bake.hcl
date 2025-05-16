variable "RELEASE" {
  default = "1.0.3"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/tensorflow"
  dockerfile = "Dockerfile"
  tags = ["runpod/tensorflow:${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
