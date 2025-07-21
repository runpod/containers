variable "RELEASE" {
  default = "1.2.1"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/oobabooga"
  dockerfile = "Dockerfile"
  tags = ["runpod/oobabooga:${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
