target "default" {
    dockerfile = "Dockerfile"
    tags = ["runpod/stable-diffusion:fast-stable-diffusion-2.1.0"]
    contexts = {
        scripts = "../../container-template"
        proxy = "../../container-template/proxy"
    }
}
