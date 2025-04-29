variable "VERSION" {
  default = "5.3.3"
}

variable "GITHUB_WORKSPACE" {
  default = "." # replaced with cwd
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/bittensor"
  dockerfile = "Dockerfile"
  tags = ["runpod/bittensor:${VERSION}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
  args = {
    VERSION = "${VERSION}"
  }
}
