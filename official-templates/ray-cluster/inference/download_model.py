"""Download MODEL_REPO into the Hugging Face cache before vLLM starts.

Run on the head by /opt/runpod/inference/start, in the background job that
then runs `vllm serve`. The base sets HF_HOME on /workspace, so when every
node mounts one network volume there, all of vLLM's workers would otherwise
download the same repo into the same cache at once, and huggingface_hub's
file locks don't hold across hosts. Downloaded here first, the workers find a
complete cache; without a shared volume, each worker still downloads its own.

The weights are exactly the files vLLM 0.32.0's default loader downloads
(DefaultModelLoader._prepare_weights and download_weights_from_hf), so no
worker finds one missing and none is fetched that it won't read; re-check
weight_patterns on a vLLM bump. Load formats served by other loaders (gguf,
bitsandbytes, ...) are left to vLLM. Beside them, the repo's top-level
config and tokenizer files.

When the Hub can't be reached (HF_HUB_OFFLINE, an outage, no egress), a
snapshot already in the cache is served as is, as vLLM itself would.

Usage: download_model.py <repo> <revision or ""> <cache dir or ""> <load format>
"""

import fnmatch
import glob
import json
import posixpath
import sys

from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download

SAFETENSORS_INDEX = "model.safetensors.index.json"
# vLLM's LoadConfig.ignore_patterns default (Llama's original/ checkpoints).
IGNORE = ["original/**/*"]
# Top-level files that are weights in some format, not config or tokenizer.
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".h5", ".msgpack", ".ot",
                   ".tflite", ".onnx", ".onnx_data", ".gguf", ".ckpt", ".npz")


def log(msg: str) -> None:
    print(f"[ray-inference] {msg}", file=sys.stderr, flush=True)


def weight_patterns(files: list[str], load_format: str,
                    indexed: list[str] | None) -> list[str] | None:
    """The allow_patterns of vLLM's weight download, or None for a load
    format another loader handles. `files` is the repo listing, `indexed` the
    files model.safetensors.index.json maps, if the repo has one."""
    if load_format == "auto":
        # vLLM serves a repo with a consolidated copy in Mistral's format.
        mistral = any(fnmatch.fnmatch(posixpath.basename(f), "consolidated*.safetensors")
                      for f in files)
        load_format = "mistral" if mistral else "hf"
    patterns = {
        # fall_back_to_pt adds *.pt to every format but the safetensors ones.
        "hf": ["*.safetensors", "*.bin", "*.pt"],
        "safetensors": ["*.safetensors"],
        "fastsafetensors": ["*.safetensors"],
        "instanttensor": ["*.safetensors"],
        "mistral": ["consolidated*.safetensors"],
        "pt": ["*.pt"],
        "npcache": ["*.bin", "*.pt"],
    }.get(load_format)
    if patterns is None:
        return None
    # download_weights_from_hf narrows them by the repo's top level: the
    # index's files, else the first pattern that matches.
    top = [f for f in files if "/" not in f]
    if "*.safetensors" in patterns and indexed:
        return [glob.escape(f) for f in sorted(set(indexed))]
    return next(([p] for p in patterns if fnmatch.filter(top, p)), None)


def config_files(files: list[str]) -> list[str]:
    """Top-level files that aren't weights: config, tokenizer, chat template."""
    return [glob.escape(f) for f in files if "/" not in f and not f.endswith(WEIGHT_SUFFIXES)]


def indexed_files(repo: str, revision: str | None, cache_dir: str | None) -> list[str]:
    path = hf_hub_download(repo, SAFETENSORS_INDEX, revision=revision, cache_dir=cache_dir)
    with open(path) as f:
        return list(json.load(f)["weight_map"].values())


def download(repo: str, revision: str | None, cache_dir: str | None, load_format: str) -> None:
    files = list_repo_files(repo, revision=revision)
    indexed = indexed_files(repo, revision, cache_dir) if SAFETENSORS_INDEX in files else None
    weights = weight_patterns(files, load_format, indexed)
    if weights is None:
        log(f"no weights to download ahead for --load-format {load_format}; vLLM downloads them")
        weights = []
    snapshot_download(repo, revision=revision, cache_dir=cache_dir,
                      allow_patterns=weights + config_files(files), ignore_patterns=IGNORE)


def main() -> int:
    repo, revision, cache_dir = sys.argv[1], sys.argv[2] or None, sys.argv[3] or None
    load_format = sys.argv[4].lower()
    try:
        download(repo, revision, cache_dir, load_format)
    except Exception as e:  # noqa: BLE001 - any failure is reported, then vLLM is skipped
        try:
            snapshot_download(repo, revision=revision, cache_dir=cache_dir, local_files_only=True)
        except Exception:  # noqa: BLE001 - no cached snapshot either
            log(f"{type(e).__name__}: {e}")
            return 1
        log(f"{type(e).__name__}: {e}; serving the snapshot already in the cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
