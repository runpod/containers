GENAI_PERF_VERSION="0.0.15"
group "cpu" {
  targets = ["cpu-ubuntu2404"]
}

group "default" {
  targets = ["cpu"]
}

target "common-base" {
  context = "nextai-templates/genai-perf"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    scripts = "container-template"
    proxy   = "container-template/proxy"
    logo    = "container-template"
  }
}

target "cpu-ubuntu2404" {
  inherits = ["common-base"]
  tags = [
    "ghcr.io/mmua/genai-perf-runpod:${GENAI_PERF_VERSION}-ubuntu2404",
    "ghcr.io/mmua/genai-perf-runpod:${GENAI_PERF_VERSION}-noble",
  ]
  args = {
    BASE_IMAGE = "ubuntu:24.04"
  }
}

# the line we change to make ci run
