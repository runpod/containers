variable "RELEASE" {
    default = "13.0.0"
}

target "default" {
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-ui-${RELEASE}"]
  contexts = {
    scripts = "../../container-template"
    proxy = "../../container-template/proxy"
  }
  args = {
    WEBUI_VERSION = "v1.10.0"
  }
  platforms = ["linux/amd64"]
}
