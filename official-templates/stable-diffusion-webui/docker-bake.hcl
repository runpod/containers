variable "RELEASE" {
    default = "10.2.0"
}

target "default" {
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-ui-${RELEASE}"]
  contexts = {
    scripts = "../../container-template"
    proxy = "../../container-template/proxy"
  }
}
