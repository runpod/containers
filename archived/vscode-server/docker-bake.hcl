variable "RELEASE" {
  default = "0.1.2"
}

variable "GITHUB_WORKSPACE" {
  default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/vscode-server"
  dockerfile = "Dockerfile"
  tags = ["runpod/vscode-server:${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
}
