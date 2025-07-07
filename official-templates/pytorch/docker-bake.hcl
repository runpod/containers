variable "TORCH_META" {
  default = {
    "2.7.1" = {
      torchvision = "0.22.1"
    }
    "2.6.0" = {
      torchvision = "0.21.0"
    }
    "2.5.1" = {
      torchvision = "0.20.1"
    }
    "2.5.0" = {
      torchvision = "0.20.0"
    }
    "2.4.1" = {
      torchvision = "0.19.1"
    }
    "2.4.0" = {
      torchvision = "0.19.0"
    }
  }
}

# We need to grab the most compatible wheel for a given CUDA version and Torch version pair
# At times, this requires grabbing a wheel built for a different CUDA version.
variable "CUDA_TORCH_COMBINATIONS" {
  default = [ 
    { cuda_version = "12.4.1", torch = "2.4.0", whl_src = "121" },
    { cuda_version = "12.4.1", torch = "2.4.1", whl_src = "121" },
    { cuda_version = "12.4.1", torch = "2.5.0", whl_src = "124" },
    { cuda_version = "12.4.1", torch = "2.5.1", whl_src = "124" },
    { cuda_version = "12.4.1", torch = "2.6.0", whl_src = "124" },
    
    { cuda_version = "12.5.1", torch = "2.5.1", whl_src = "121" },
    { cuda_version = "12.5.1", torch = "2.6.0", whl_src = "124" },
    
    { cuda_version = "12.6.3", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "12.6.3", torch = "2.7.1", whl_src = "126" },
    
    { cuda_version = "12.8.1", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "12.8.1", torch = "2.7.1", whl_src = "128" },
    
    { cuda_version = "12.9.0", torch = "2.6.0", whl_src = "126" },
    { cuda_version = "12.9.0", torch = "2.7.1", whl_src = "128" },
  ]
}

variable "COMPATIBLE_BUILDS" {
  default = flatten([
    for combo in CUDA_TORCH_COMBINATIONS : [
      for cuda in CUDA_VERSIONS : [
        for ubuntu in UBUNTU_VERSIONS : {
          ubuntu_version = ubuntu.version
          ubuntu_name    = ubuntu.name
          ubuntu_alias   = ubuntu.alias
          cuda_version   = cuda.version
          cuda_code      = replace(cuda.version, ".", "")
          wheel_src      = combo.whl_src
          torch          = combo.torch
          torch_code     = replace(combo.torch, ".", "")
          torch_vision   = TORCH_META[combo.torch].torchvision
        } if cuda.version == combo.cuda_version && contains(cuda.ubuntu, ubuntu.version)
      ]
    ]
  ])
}

group "dev" {
  targets = ["pytorch-ubuntu2204-cu1241-torch260"]
}

group "default" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "pytorch-${build.ubuntu_name}-cu${replace(build.cuda_version, ".", "")}-torch${build.torch_code}"
  ]
}

target "pytorch-base" {
  context = "official-templates/pytorch"
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
}

target "pytorch-matrix" {
  matrix = {
    build = COMPATIBLE_BUILDS
  }
  
  name = "pytorch-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}"
  
  inherits = ["pytorch-base"]
  
  args = {
    BASE_IMAGE = "runpod/base:${RELEASE_VERSION}-${build.ubuntu_name}-cuda${build.cuda_version}"
    WHEEL_SRC = build.wheel_src
    TORCH = "torch==${build.torch} torchvision==${build.torch_vision} torchaudio==${build.torch}"
  }
  
  tags = [
    "runpod/pytorch:${RELEASE_VERSION}-${build.ubuntu_name}-cu${build.cuda_code}-torch${build.torch_code}",
    "runpod/pytorch:${RELEASE_VERSION}-cu${build.cuda_code}-torch${build.torch_code}-${build.ubuntu_name}",
  ]
}

# the line we change to make ci run
