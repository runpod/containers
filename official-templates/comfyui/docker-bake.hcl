# === Version Pins (single source of truth) ===
variable "COMFYUI_VERSION" {
  default = "v0.30.0"
}
variable "MANAGER_SHA" {
  default = "c352b16bb186"
}
variable "KJNODES_SHA" {
  default = "bc8e4ce4254b"
}
variable "CIVICOMFY_SHA" {
  default = "555e984bbcb0"
}
variable "RUNPODDIRECT_SHA" {
  default = "809065c9d2f3"
}
variable "FILEBROWSER_VERSION" {
  default = "v2.59.0"
}
variable "FILEBROWSER_SHA256" {
  default = "8cd8c3baecb086028111b912f252a6e3169737fa764b5c510139e81f9da87799"
}

variable "CUDA_TORCH_COMBINATIONS" {
  default = [
    { cuda_version = "12.8", 
      // torch_index_suffix = "cu128", 
      // cuda_version_dash = "12-8", 
      // torch_version = "2.10.0+cu128", 
      // torchvision_version = "0.25.0+cu128", 
      // torchaudio_version = "2.10.0+cu128",
      torch_version = "2.10.0", 
      torchvision_version = "0.25.0", 
      torchaudio_version = "2.10.0"  
    },
    { cuda_version = "13.0", 
      // torch_index_suffix = "cu130",
      // cuda_version_dash = "13-0", 
      torch_version = "2.10.0", 
      torchvision_version = "0.25.0", 
      torchaudio_version = "2.10.0" 
    }
  ]
}

variable "COMPATIBLE_BUILDS" {
  default = flatten([
    for combination in CUDA_TORCH_COMBINATIONS:
      [
        { cuda_version = combination.cuda_version, 
          cuda_version_code = replace(combination.cuda_version, ".", ""),
          cuda_version_dash = replace(combination.cuda_version, ".", "-"),
          torch_index_suffix = "cu${combination.cuda_version_code}",
          torch_version = "${combination.torch_version}+${combination.torch_index_suffix}",
          torchvision_version = "${combination.torchvision_version}+${combination.torch_index_suffix}",
          torchaudio_version = "${combination.torchaudio_version}+${combination.torch_index_suffix}",
         },
      ]
    ]
  )
}

group "default" {
  targets = [
    for combination in COMPATIBLE_BUILDS:
      "cuda${combination.cuda_version_code}"
  ]
}

group "cuda128" {
  targets = [
    for combination in COMPATIBLE_BUILDS:
      "cuda${combination.cuda_version_code}"
      if combination.cuda_version == "12.8"
  ]
}

group "cuda13" {

  targets = [
    for combination in COMPATIBLE_BUILDS:
      "cuda${combination.cuda_version_code}"
      if combination.cuda_version == "13.0"
  ]
}

# Common settings for all targets (defaults to regular CUDA 12.8 / cu128)
target "common" {
  context    = "."
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "comfyui-matrix" {
  inherits = ["common"]
  matrix = {
    build = COMPATIBLE_BUILDS
  }

  name = "cuda${build.cuda_version_code}"

  args = {
    COMFYUI_VERSION     = COMFYUI_VERSION
    MANAGER_SHA         = MANAGER_SHA
    KJNODES_SHA         = KJNODES_SHA
    CIVICOMFY_SHA       = CIVICOMFY_SHA
    RUNPODDIRECT_SHA    = RUNPODDIRECT_SHA
    FILEBROWSER_VERSION = FILEBROWSER_VERSION
    FILEBROWSER_SHA256  = FILEBROWSER_SHA256
    TORCH_VERSION       = build.torch_version
    TORCHVISION_VERSION = build.torchvision_version
    TORCHAUDIO_VERSION  = build.torchaudio_version
    CUDA_VERSION_DASH   = build.cuda_version_dash
    TORCH_INDEX_SUFFIX  = build.torch_index_suffix
  }

  tags = [
    "runpod/comfyui:${RELEASE_VERSION}${RELEASE_SUFFIX}-comfyui${COMFYUI_VERSION}-cuda${build.cuda_version}"
  ]
}