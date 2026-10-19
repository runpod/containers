#!/usr/bin/env python3
"""Pre-populate ComfyUI-Manager cache at Docker build time.

Fetches the ComfyRegistry node list and writes it under the cache name
ComfyUI-Manager derives from the request URI, so the first cold start skips
the slow paginated fetch from api.comfy.org (~130 requests).

Cache expires after 24h; after that Manager re-fetches in the background.

Only the registry is pre-baked. The channel lists (custom-node-list.json and
friends) ship inside the comfyui_manager package, and a pip-installed Manager
reads them from the package unless a cache file exists — a pre-baked one would
never be refreshed, so those are left to the package copy.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen, Request

CACHE_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/comfyui-baked/user/__manager/cache")
COMFYUI_VERSION = sys.argv[2] if len(sys.argv) > 2 else "unknown"

# Paginated ComfyRegistry API. Manager keys the cache on the bare URI and asks
# for the pages with these parameters (cnr_utils._get_cnr_data); form_factor is
# what a git checkout on Linux reports.
REGISTRY_URL = "https://api.comfy.org/nodes"
REGISTRY_PAGE_SIZE = 30
FORM_FACTOR = "git-linux"


def simple_hash(input_string: str) -> int:
    """Mirror ComfyUI-Manager's manager_util.simple_hash."""
    hash_value = 0
    for char in input_string:
        hash_value = (hash_value * 31 + ord(char)) % (2**32)
    return hash_value


def cache_path(uri: str) -> Path:
    """Mirror ComfyUI-Manager's manager_util.get_cache_path."""
    name = uri.rsplit("/", 1)[-1].replace("&", "_").replace("?", "_").replace("=", "_")
    return CACHE_DIR / f"{simple_hash(uri)}_{name}.json"


def fetch_json(url: str) -> dict:
    """Fetch URL and return the parsed body."""
    req = Request(url, headers={"User-Agent": "ComfyUI-Docker-Build"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_registry_all() -> dict:
    """Fetch all pages from the ComfyRegistry API, keyed by node id like Manager does."""
    nodes = {}
    page = 1
    total_pages = 1

    while page <= total_pages:
        url = (
            f"{REGISTRY_URL}?page={page}&limit={REGISTRY_PAGE_SIZE}"
            f"&comfyui_version={COMFYUI_VERSION}&form_factor={FORM_FACTOR}"
        )
        data = fetch_json(url)
        total_pages = data["totalPages"]
        for node in data["nodes"]:
            nodes[node["id"]] = node
        if page % 20 == 0 or page == total_pages:
            print(f"  Registry: page {page}/{total_pages} ({len(nodes)} nodes total)")
        page += 1

    for node in nodes.values():
        if "latest_version" not in node:
            node["latest_version"] = dict(version="nightly")

    return {"nodes": list(nodes.values())}


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pre-populating ComfyUI-Manager cache in {CACHE_DIR}")
    print(f"  ComfyRegistry (paginated), comfyui_version={COMFYUI_VERSION}")

    # Non-fatal: if the registry is down, Manager will fetch on first start
    try:
        registry_data = fetch_registry_all()
    except Exception as e:
        print(f"  WARNING: Registry fetch failed ({e}), skipping — Manager will fetch on first start")
        return

    target = cache_path(REGISTRY_URL)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(registry_data, f, indent=4, sort_keys=True)
    print(f"  Cached {len(registry_data['nodes'])} registry nodes in {target.name}")


if __name__ == "__main__":
    main()
