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
    WEBUI_VERSION = "v1.9.3"
    TORCH_VERSION = "2.1.2+cu118"
    XFORMERS_VERSION = "0.0.23.post1+cu118"
  }
}
