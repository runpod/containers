target "default" {
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-ui-8.0.3"]
  contexts = {
    scripts = "../../container-template"
    proxy = "../../container-template/proxy"
    models = "../../models"
  }
}
