variable "RELEASE" {
  default = "12.0.0"
}

variable "GITHUB_WORKSPACE" {
    default = "."
}

target "default" {
  context = "${GITHUB_WORKSPACE}/official-templates/stable-diffusion-webui"
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-ui-${RELEASE}"]
  contexts = {
    scripts = "container-template"
    proxy = "container-template/proxy"
  }
  args = {
    WEBUI_VERSION = "v1.8.0"
    TORCH_VERSION = "2.1.2+cu118"
    XFORMERS_VERSION = "0.0.23.post1+cu118"
  }
}
