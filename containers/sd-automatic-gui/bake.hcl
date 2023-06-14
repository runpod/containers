target "web-automatic" {
  dockerfile = "Dockerfile"
  tags = ["runpod/stable-diffusion:web-automatic-8.0.3"]
  contexts = {
    scripts = "../../scripts"
    models = "../../models"
  }
}
