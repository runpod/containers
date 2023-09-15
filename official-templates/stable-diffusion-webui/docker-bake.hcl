variable "RELEASE" {
    default = "10.2.1"
}

target "default" {
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-ui-${RELEASE}"]
  contexts = {
    scripts = "../../container-template"
    proxy = "../../container-template/proxy"
  }
  args = {
    WEBUI_VERSION = "v1.6.0"
  }
}
