# === Version Pins (single source of truth) ===
variable "COMFYUI_VERSION" {
  default = "v0.35.0"
}
variable "MANAGER_SHA" {
  default = "9d4cceea1351"
}
variable "KJNODES_SHA" {
  default = "57105374f47d"
}
variable "CIVICOMFY_SHA" {
  default = "555e984bbcb0"
}
variable "RUNPODDIRECT_SHA" {
  default = "9e32b1a09577"
}
variable "FILEBROWSER_VERSION" {
  default = "v2.59.0"
}
variable "FILEBROWSER_SHA256" {
  default = "8cd8c3baecb086028111b912f252a6e3169737fa764b5c510139e81f9da87799"
}

# The 13.2 image is the only one on the newer stack: the cu132 index has no
# torch before 2.12.0. Keeping 12.8 and 13.0 on 2.10.0 leaves existing volumes
# alone — torch 2.11 dropped Volta (SM 7.0), 2.13 changed the C++ ABI, and
# torchvision 0.26 removed the video I/O, so every one of those breaks lands
# only on a variant nobody is running yet, isolated in its own venv.
#
# torchaudio ended at 2.11.0 and cu132 never got it, so 13.2 takes the plain
# PyPI wheel — identical in size to the +cu130 one, since after 2.9 moved I/O to
# torchcodec it ships no CUDA kernels. Its version is spelled out per row rather
# than built from the suffix: `==2.11.0` also matches `2.11.0+cu130`, and pip
# prefers the local build, which would then fail the post-install check.
variable "CUDA_TORCH_COMBINATIONS" {
  default = [
    { cuda_version = "12.8",
      torch_index_suffix = "cu128",
      venv_name = ".venv-cu128",
      torch_version = "2.10.0",
      torchvision_version = "0.25.0",
      torchaudio_version = "2.10.0+cu128"
    },
    { cuda_version = "13.0",
      torch_index_suffix = "cu130",
      venv_name = ".venv-cu128",
      torch_version = "2.10.0",
      torchvision_version = "0.25.0",
      torchaudio_version = "2.10.0+cu130"
    },
    { cuda_version = "13.2",
      torch_index_suffix = "cu132",
      venv_name = ".venv-cu132",
      torch_version = "2.13.0",
      torchvision_version = "0.28.0",
      torchaudio_version = "2.11.0"
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
          torch_index_suffix = combination.torch_index_suffix,
          venv_name = combination.venv_name,
          torch_version = "${combination.torch_version}+${combination.torch_index_suffix}",
          torchvision_version = "${combination.torchvision_version}+${combination.torch_index_suffix}",
          torchaudio_version = combination.torchaudio_version,
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

# group "cuda132" {

#   targets = [
#     for combination in COMPATIBLE_BUILDS:
#       "cuda${combination.cuda_version_code}"
#       if combination.cuda_version == "13.2"
#   ]
# }

# Common settings for all targets (defaults to regular CUDA 12.8 / cu128)
target "common" {
  context    = "official-templates/comfyui"
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
    COMFYUI_VENV_NAME   = build.venv_name
  }

  tags = [
    "runpod/comfyui:${RELEASE_VERSION}${RELEASE_SUFFIX}-comfyui${COMFYUI_VERSION}-cuda${build.cuda_version}"
  ]
}