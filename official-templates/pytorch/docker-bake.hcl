# https://pytorch.org/get-started/locally/

variable "TORCH_META" {
  default = {
    # torchcodec backs torchaudio.load/save from 2.9 on; 0.9.x is the build for
    # torch 2.9. It replaces torchaudio.io, removed in 2.9, as the NVDEC path.
    "2.9.1" = {
      torchcodec = "0.9.1"
    }
    "2.9.0" = {
      torchvision = "0.24.0"
      torchcodec  = "0.9.1"
    }
    "2.8.0" = {
      torchvision = "0.23.0"
    }
    "2.7.1" = {
      torchvision = "0.22.1"
    }
    "2.6.0" = {
      torchvision = "0.21.0"
    }
    # torchaudio's last release is 2.11.0 — it was dropped from the PyTorch
    # release process starting with 2.12 (decode/encode moved to TorchCodec).
    # Upstream states 2.11.0 is compatible with future torch versions, and its
    # wheel declares no dependencies, so it will not downgrade torch.
    # torchaudio.load/save are torchcodec wrappers from 2.9 on and raise
    # ImportError without it. torchcodec 0.13+ declares torch >= 2.11, so one
    # pin covers all three.
    "2.12.0" = {
      torchvision = "0.27.0"
      torchaudio  = "2.11.0"
      torchcodec  = "0.16.0"
    }
    "2.12.1" = {
      torchvision = "0.27.1"
      torchaudio  = "2.11.0"
      torchcodec  = "0.16.0"
    }
    "2.13.0" = {
      torchvision = "0.28.0"
      torchaudio  = "2.11.0"
      torchcodec  = "0.16.0"
    }
  }
}

# We need to grab the most compatible wheel for a given CUDA version and Torch version pair
# At times, this requires grabbing a wheel built for a different CUDA version.
# Torch 2.12+ ships no cu128 wheels: CUDA 12.8 was deprecated in 2.12 and
# removed from the build matrix in 2.13. cu129 is the substitute for the
# 12.x bases — it stays in the 2.12/2.13 release matrices (see CUDA_ARCHES
# in .github/scripts/generate_binary_build_matrix.py on release/2.12 and
# release/2.13) and carries the same SM list as cu130 on x86_64. The other
# 12.x option, cu126, stops at sm_90 and ships no PTX, so it cannot run on
# Blackwell at all — avoid it for these versions.
#
# 2.12.0 is CUDA 13 only: cu129 landed in the 2.12 matrix after .0, so
# 2.12.0+cu129 wheels do not exist. 2.12.1 covers the 12.x bases instead.
variable "CUDA_TORCH_COMBINATIONS" {
  default = [
    { cuda_version = "12.8.1", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "12.8.1", torch = "2.7.1", whl_src = "128" },
    { cuda_version = "12.8.1", torch = "2.8.0", whl_src = "128" },
    { cuda_version = "12.8.1", torch = "2.9.0", whl_src = "128" },
    { cuda_version = "12.8.1", torch = "2.9.1", whl_src = "128" },
    { cuda_version = "12.8.1", torch = "2.12.1", whl_src = "129" },
    { cuda_version = "12.8.1", torch = "2.13.0", whl_src = "129" },
    
    { cuda_version = "12.9.0", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "12.9.0", torch = "2.7.1", whl_src = "128" },
    { cuda_version = "12.9.0", torch = "2.8.0", whl_src = "129" },
    # codec_src: the cu129 index has no torchcodec for torch 2.9 at all (it goes
    # 0.7.0 -> 0.10.0), so take the cu128 build. Same CUDA major, so the runtime
    # sonames match. Defaults to whl_src everywhere else.
    { cuda_version = "12.9.0", torch = "2.9.0", whl_src = "129", codec_src = "128" },
    { cuda_version = "12.9.0", torch = "2.9.1", whl_src = "129", codec_src = "128" },
    { cuda_version = "12.9.0", torch = "2.12.1", whl_src = "129" },
    { cuda_version = "12.9.0", torch = "2.13.0", whl_src = "129" },

    { cuda_version = "13.0.0", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "13.0.0", torch = "2.7.1", whl_src = "128" },
    { cuda_version = "13.0.0", torch = "2.8.0", whl_src = "129" },
    { cuda_version = "13.0.0", torch = "2.9.0", whl_src = "130" },
    { cuda_version = "13.0.0", torch = "2.9.1", whl_src = "130" },
    { cuda_version = "13.0.0", torch = "2.12.0", whl_src = "130" },
    { cuda_version = "13.0.0", torch = "2.12.1", whl_src = "130" },
    { cuda_version = "13.0.0", torch = "2.13.0", whl_src = "130" },
  ]
}

variable "COMPATIBLE_BUILDS" {
  default = flatten([
    for combo in CUDA_TORCH_COMBINATIONS : [
      for cuda in CUDA_VERSIONS : [
        for ubuntu in UBUNTU_VERSIONS : {
          ubuntu_version = ubuntu.version
          ubuntu_name    = ubuntu.name
          cuda_version   = cuda.version
          cuda_code      = replace(cuda.version, ".", "")
          wheel_src      = combo.whl_src
          torch          = combo.torch
          torch_code     = replace(combo.torch, ".", "")
          torch_vision   = lookup(TORCH_META[combo.torch], "torchvision", "")
          torch_audio    = lookup(TORCH_META[combo.torch], "torchaudio", combo.torch)
          torch_codec    = lookup(TORCH_META[combo.torch], "torchcodec", "")
          codec_src      = lookup(combo, "codec_src", combo.whl_src)
        } if cuda.version == combo.cuda_version && contains(cuda.ubuntu, ubuntu.version)
      ]
    ]
  ])
}

group "dev" {
  targets = ["pytorch-ubuntu2404-cu1281-torch280"]
}

group "default" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "pytorch-${build.ubuntu_name}-cu${replace(build.cuda_version, ".", "")}-torch${build.torch_code}"
  ]
}

# Per-CUDA-major groups so CI can shard the matrix across separate runners.
# Bake does not expand glob patterns in target arguments, so we need explicit
# groups (or full target names) — globs only work via `--list` / `--print`.
group "cu1281" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "pytorch-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"
      if build.cuda_code == "1281"
  ]
}

group "cu1290" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "pytorch-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"
      if build.cuda_code == "1290"
  ]
}

group "cu1300" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "pytorch-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"
      if build.cuda_code == "1300"
  ]
}

target "pytorch-base" {
  context = "official-templates/pytorch"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
  contexts = {
    requirements = "official-templates/pytorch"
  }
}

target "pytorch-matrix" {
  matrix = {
    build = COMPATIBLE_BUILDS
  }
  
  name = "pytorch-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"
  
  inherits = ["pytorch-base"]
  
  args = {
    BASE_IMAGE = "runpod/base:${RELEASE_VERSION}${RELEASE_SUFFIX}-cuda${build.cuda_code}-${build.ubuntu_name}"
    WHEEL_SRC = build.wheel_src
    TORCH = "torch==${build.torch}${build.torch_vision != "" ? " torchvision==${build.torch_vision}" : ""}${build.torch_audio != "" ? " torchaudio==${build.torch_audio}" : ""}"
    TORCHCODEC = build.torch_codec != "" ? "torchcodec==${build.torch_codec}" : ""
    CODEC_SRC = build.codec_src
  }
  
  tags = [
    "runpod/pytorch:${RELEASE_VERSION}${RELEASE_SUFFIX}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}",
  ]
}
