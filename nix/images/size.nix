# `nix run .#image-size -- [image ...]`: build the Nix images and compare
# their compressed size (≈ what a pod pulls) with the published image each one
# stands in for. Prints a Markdown table.

{ pkgs }:

pkgs.writeShellApplication {
  name = "image-size";
  runtimeInputs = with pkgs; [
    coreutils
    curl
    jq
    pigz
  ];
  text = ''
    # Nix image -> the published image it replaces. Bump with new releases.
    declare -A published=(
      [nix-base-cpu]=base:1.6.0-ubuntu2404
      [nix-base-cpu-runtime]=base:1.6.0-ubuntu2404
      [nix-base-cuda]=base:1.6.0-cuda1320-ubuntu2404
      [nix-pytorch-cuda]=pytorch:1.6.0-cu1320-torch2130-ubuntu2404
      [nix-pytorch-rocm]=rocm:1.6.0-rocm644-ubuntu2404-py312-pytorch271
    )
    order=(nix-base-cpu nix-base-cpu-runtime nix-base-cuda nix-pytorch-cuda nix-pytorch-rocm)
    if [ "$#" -gt 0 ]; then order=("$@"); fi

    # nixpkgs' CUDA packages are unfree, so cache.nixos.org doesn't have them;
    # the NixOS CUDA team's cache does. Takes effect for trusted users.
    cuda_cache=(
      --option extra-substituters https://cache.nixos-cuda.org
      --option extra-trusted-public-keys
      cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M=
    )

    mb() { echo $(( ($1 + 500000) / 1000000 )); }

    echo "| Nix image | Nix (gzip) | published image | published | change |"
    echo "| --- | ---: | --- | ---: | ---: |"
    for image in "''${order[@]}"; do
      ref=''${published[$image]:?unknown image: $image}
      stream=$(nix build --no-link --print-out-paths "''${cuda_cache[@]}" ".#$image")
      nix_bytes=$("$stream" 2>/dev/null | pigz -6 | wc -c)
      pub_bytes=$(curl -fsS "https://hub.docker.com/v2/repositories/runpod/''${ref%%:*}/tags/''${ref#*:}" |
        jq '[.images[] | select(.architecture == "amd64")][0].size')
      change=$(( (nix_bytes - pub_bytes) * 100 / pub_bytes ))
      echo "| $image | $(mb "$nix_bytes") MB | runpod/$ref | $(mb "$pub_bytes") MB | $change% |"
    done
  '';
}
