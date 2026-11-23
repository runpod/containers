# === Version Pins (single source of truth) ===

# Each release is built for every CUDA variant and tagged with its version, so
# they ship side by side. manager_version must match the release's own
# manager_requirements.txt; the build checks it.
variable "COMFYUI_VERSIONS" {
  default = [
    { version = "v0.44.0", manager_version = "4.2.2" },
    { version = "v0.45.0", manager_version = "4.2.2" }
  ]
}
variable "KJNODES_SHA" {
  default = "57105374f47d"
}
variable "CIVICOMFY_SHA" {
  default = "555e984bbcb0"
}
# ComfyUI-RunpodDirect v.1.0.13
variable "RUNPODDIRECT_SHA" {
  default = "1c0dd562dc3f"
}
# FileBrowser is archived upstream (2026-09-01); v2.63.23 is its last release.
# The Dockerfile builds it from source with a current Go and patched modules.
# FILEBROWSER_COMMIT is the commit the tag points to; the build checks it.
variable "FILEBROWSER_VERSION" {
  default = "v2.63.23"
}
variable "FILEBROWSER_COMMIT" {
  default = "e8a388f840173580116f2743813d03b22286e44e"
}

# The 13.2 image is the only one on the newer stack: the cu132 index has no
# torch before 2.12.0. Keeping 12.8 and 13.0 on 2.10.0 leaves existing volumes
# alone — torch 2.11 dropped Volta (SM 7.0), 2.13 changed the C++ ABI, and
# torchvision 0.26 removed the video I/O, so every one of those breaks lands
# only on a variant nobody is running yet, isolated in its own venv.
#
# torchaudio ended at 2.11.0 and cu132 never got it, so 13.2 takes the +cpu
# build. Its import calls _check_cuda_version(), which raises when its CUDA does
# not match torch's — and every CUDA build of 2.11.0, including the one on PyPI,
# is cu130. The +cpu wheel reports no CUDA at all, so the check is skipped;
# nothing is lost because after 2.9 moved I/O to torchcodec the remaining
# transforms are torch ops that still run on the GPU.
#
# Hence a separate index per row. The version is spelled out rather than built
# from the suffix so the post-install check compares against what pip resolved.
# install_cuda_compat bakes NVIDIA's forward-compat libcuda (cuda-compat-X-Y)
# into the image so it can run on hosts whose driver is older than its CUDA
# (e.g. a cu130 image on a 12.8/12.9 host). start.sh enables it only after a
# cuInit() probe succeeds, so it is a no-op on newer drivers and on GPUs NVIDIA
# does not support for forward compat (GeForce). 12.8 is off: no evidence of
# sub-570 hosts, and it would add ~300 MB (installed: cuda-compat-13-0 is
# ~310 MB, cuda-compat-13-2 ~410 MB).
#
# SageAttention is compiled against one exact torch + CUDA pair, so each row
# pins its own prebuilt wheel from https://github.com/runpod/sageattention
# (release 0.2.0; every wheel there passed GPU tests on SM 8.0/8.6/8.9/9.0/12.0).
# Leave the three fields empty for a variant that has no wheel: it then ships
# without SageAttention.
variable "CUDA_TORCH_COMBINATIONS" {
  default = [
    { cuda_version = "12.8",
      install_cuda_compat = false,
      torch_index_suffix = "cu128",
      torchaudio_index_suffix = "cu128",
      torch_version = "2.10.0",
      torchvision_version = "0.25.0",
      torchaudio_version = "2.10.0+cu128",
      sageattention_version = "2.2.0+torch2.10.0.cu128.sm90fix1",
      sageattention_wheel_url = "https://github.com/runpod/sageattention/releases/download/0.2.0/sageattention-2.2.0%2Btorch2.10.0.cu128.sm90fix1-cp312-cp312-linux_x86_64.whl",
      sageattention_sha256 = "e46dda74dd1ca41e231e33af03b8bdbe1f5f3de4802472ed86ea3162fb596fb0"
    },
    { cuda_version = "13.0",
      install_cuda_compat = true,
      torch_index_suffix = "cu130",
      torchaudio_index_suffix = "cu130",
      torch_version = "2.10.0",
      torchvision_version = "0.25.0",
      torchaudio_version = "2.10.0+cu130",
      sageattention_version = "2.2.0+torch2.10.0.cu130.sm90fix1",
      sageattention_wheel_url = "https://github.com/runpod/sageattention/releases/download/0.2.0/sageattention-2.2.0%2Btorch2.10.0.cu130.sm90fix1-cp312-cp312-linux_x86_64.whl",
      sageattention_sha256 = "4277a667b6ba5f8b33e20fb44cb2399d571b44a159225242db4aaf004f2498ce"
    },
    { cuda_version = "13.2",
      install_cuda_compat = true,
      torch_index_suffix = "cu132",
      torchaudio_index_suffix = "cpu",
      torch_version = "2.13.0",
      torchvision_version = "0.28.0",
      torchaudio_version = "2.11.0+cpu",
      sageattention_version = "2.2.0+torch2.13.0.cu132.sm90fix1",
      sageattention_wheel_url = "https://github.com/runpod/sageattention/releases/download/0.2.0/sageattention-2.2.0%2Btorch2.13.0.cu132.sm90fix1-cp312-cp312-linux_x86_64.whl",
      sageattention_sha256 = "0e940815cb1e9bccffcde5303f095c324f2174e2fe0100eae7614c92dbd1050b"
    }
  ]
}

# No ComfyUI release pins torch, so the stack and venv_name follow the CUDA
# variant alone — a pod moving between ComfyUI versions keeps its venv.
variable "COMPATIBLE_BUILDS" {
  default = flatten([
    for comfyui in COMFYUI_VERSIONS:
      [
        for combination in CUDA_TORCH_COMBINATIONS:
          { comfyui_version = comfyui.version,
            # v0.45.0 -> 0450, for target and group names
            comfyui_version_code = replace(replace(comfyui.version, "v", ""), ".", ""),
            manager_version = comfyui.manager_version,
            cuda_version = combination.cuda_version,
            cuda_version_code = replace(combination.cuda_version, ".", ""),
            cuda_version_dash = replace(combination.cuda_version, ".", "-"),
            torch_index_suffix = combination.torch_index_suffix,
            torchaudio_index_suffix = combination.torchaudio_index_suffix,
            torch_version = "${combination.torch_version}+${combination.torch_index_suffix}",
            torchvision_version = "${combination.torchvision_version}+${combination.torch_index_suffix}",
            torchaudio_version = combination.torchaudio_version,
            install_cuda_compat = combination.install_cuda_compat,
            sageattention_version = combination.sageattention_version,
            sageattention_wheel_url = combination.sageattention_wheel_url,
            sageattention_sha256 = combination.sageattention_sha256,
          }
      ]
    ]
  )
}

# One group per CUDA variant — how CI shards the build. No per-release group:
# adding a version stays one line in COMFYUI_VERSIONS.
group "default" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "comfyui${build.comfyui_version_code}-cuda${build.cuda_version_code}"
  ]
}

group "cuda128" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "comfyui${build.comfyui_version_code}-cuda${build.cuda_version_code}"
      if build.cuda_version == "12.8"
  ]
}

group "cuda130" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "comfyui${build.comfyui_version_code}-cuda${build.cuda_version_code}"
      if build.cuda_version == "13.0"
  ]
}

group "cuda132" {
  targets = [
    for build in COMPATIBLE_BUILDS:
      "comfyui${build.comfyui_version_code}-cuda${build.cuda_version_code}"
      if build.cuda_version == "13.2"
  ]
}

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

  name = "comfyui${build.comfyui_version_code}-cuda${build.cuda_version_code}"

  args = {
    COMFYUI_VERSION     = build.comfyui_version
    MANAGER_VERSION     = build.manager_version
    KJNODES_SHA         = KJNODES_SHA
    CIVICOMFY_SHA       = CIVICOMFY_SHA
    RUNPODDIRECT_SHA    = RUNPODDIRECT_SHA
    FILEBROWSER_VERSION = FILEBROWSER_VERSION
    FILEBROWSER_COMMIT  = FILEBROWSER_COMMIT
    TORCH_VERSION       = build.torch_version
    TORCHVISION_VERSION = build.torchvision_version
    TORCHAUDIO_VERSION  = build.torchaudio_version
    CUDA_VERSION_DASH   = build.cuda_version_dash
    TORCH_INDEX_SUFFIX  = build.torch_index_suffix
    TORCHAUDIO_INDEX_SUFFIX = build.torchaudio_index_suffix
    INSTALL_CUDA_COMPAT = build.install_cuda_compat ? "true" : "false"
    SAGEATTENTION_VERSION   = build.sageattention_version
    SAGEATTENTION_WHEEL_URL = build.sageattention_wheel_url
    SAGEATTENTION_SHA256    = build.sageattention_sha256
  }

  tags = [
    "runpod/comfyui${REPO_SUFFIX}:${RELEASE_VERSION}${RELEASE_SUFFIX}-comfyui${build.comfyui_version}-cuda${build.cuda_version}"
  ]
}