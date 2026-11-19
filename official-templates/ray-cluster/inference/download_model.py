"""Download MODEL_REPO into the Hugging Face cache before vLLM starts.

Run on the head by /opt/runpod/inference/start, in the background job that
then runs `vllm serve`. The base sets HF_HOME on /workspace, so when every
node mounts one network volume there, all of vLLM's workers would otherwise
download the same repo into the same cache at once, and huggingface_hub's
file locks don't hold across hosts. Downloaded here first, the workers find a
complete cache; without a shared volume, each worker still downloads its own.

Only what vLLM's default loader reads: the repo's files, minus the weight
formats it skips. It loads the first of safetensors, bin and pt the repo has,
only the safetensors model.safetensors.index.json lists when there is one,
and never original/: repos such as Mistral's and Llama's carry a second,
consolidated copy of the weights.

Usage: download_model.py <repo> <revision or ""> <cache dir or "">
"""

import fnmatch
import json
import sys

from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download

# vLLM's preference order for --load-format auto.
WEIGHT_FORMATS = ["*.safetensors", "*.bin", "*.pt"]
SAFETENSORS_INDEX = "model.safetensors.index.json"
# Never read by vLLM: other frameworks' weights and the consolidated copy.
NEVER_LOADED = ["original/*", "*.pth", "*.h5", "*.msgpack", "*.ot",
                "*.tflite", "onnx/*", "*.gguf"]


def log(msg: str) -> None:
    print(f"[ray-inference] {msg}", file=sys.stderr, flush=True)


def ignore_patterns(files: list[str], indexed: set[str] | None = None) -> list[str]:
    """Patterns for the files vLLM won't read: every weight format but the
    first one present, safetensors outside `indexed` (the index's files, if
    the repo has one), and NEVER_LOADED."""
    loaded = [f for f in files if not fnmatch.fnmatch(f, "original/*")]
    chosen = next((p for p in WEIGHT_FORMATS if fnmatch.filter(loaded, p)), None)
    unindexed = []
    if chosen == "*.safetensors" and indexed:
        unindexed = [f for f in fnmatch.filter(loaded, chosen) if f not in indexed]
    return [p for p in WEIGHT_FORMATS if p != chosen] + unindexed + NEVER_LOADED


def indexed_files(repo: str, revision: str | None, cache_dir: str | None) -> set[str]:
    path = hf_hub_download(repo, SAFETENSORS_INDEX, revision=revision, cache_dir=cache_dir)
    with open(path) as f:
        return set(json.load(f)["weight_map"].values())


def main() -> int:
    repo, revision, cache_dir = sys.argv[1], sys.argv[2] or None, sys.argv[3] or None
    try:
        files = list_repo_files(repo, revision=revision)
        indexed = indexed_files(repo, revision, cache_dir) if SAFETENSORS_INDEX in files else None
        snapshot_download(repo, revision=revision, cache_dir=cache_dir,
                          ignore_patterns=ignore_patterns(files, indexed))
    except Exception as e:  # noqa: BLE001 - any failure is reported, then vLLM is skipped
        log(f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
