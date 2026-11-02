#!/usr/bin/env python3
"""Pre-populate ComfyUI-Manager cache at Docker build time.

Downloads the registry JSON files and saves them with the CRC32-prefixed
filenames that ComfyUI-Manager expects, so the first cold start skips
the slow paginated fetch from api.comfy.org (~127 requests).

Cache expires after 24h; after that Manager re-fetches in the background.
"""

import json
import sys
import zlib
from pathlib import Path
from urllib.request import urlopen, Request

CACHE_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/comfyui-baked/user/__manager/cache")

# GitHub-hosted JSON files (fast, single request each)
GITHUB_URLS = [
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/alter-list.json",
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/model-list.json",
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/github-stats.json",
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json",
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json",
]

# Paginated ComfyRegistry API
REGISTRY_URL = "https://api.comfy.org/nodes"
REGISTRY_PAGE_SIZE = 30


def cache_filename(url: str) -> str:
    """Compute CRC32-prefixed filename matching ComfyUI-Manager's convention."""
    h = zlib.crc32(url.encode()) & 0xFFFFFFFF
    name = url.rsplit("/", 1)[-1]
    if not name.endswith(".json"):
        name += ".json"
    return f"{h}_{name}"


def fetch_json(url: str) -> bytes:
    """Fetch URL and return raw bytes."""
    req = Request(url, headers={"User-Agent": "ComfyUI-Docker-Build"})
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_registry_all() -> list:
    """Fetch all pages from the ComfyRegistry API."""
    all_nodes = []
    page = 1

    # First request to get total pages
    url = f"{REGISTRY_URL}?page={page}&limit={REGISTRY_PAGE_SIZE}"
    data = json.loads(fetch_json(url))
    total_pages = data["totalPages"]
    all_nodes.extend(data["nodes"])
    print(f"  Registry: page 1/{total_pages} ({len(data['nodes'])} nodes)")

    for page in range(2, total_pages + 1):
        url = f"{REGISTRY_URL}?page={page}&limit={REGISTRY_PAGE_SIZE}"
        data = json.loads(fetch_json(url))
        all_nodes.extend(data["nodes"])
        if page % 20 == 0 or page == total_pages:
            print(f"  Registry: page {page}/{total_pages} ({len(all_nodes)} nodes total)")

    return all_nodes


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pre-populating ComfyUI-Manager cache in {CACHE_DIR}")

    # Fetch GitHub JSON files
    for url in GITHUB_URLS:
        fname = cache_filename(url)
        print(f"  Fetching {url.rsplit('/', 1)[-1]}")
        data = fetch_json(url)
        (CACHE_DIR / fname).write_bytes(data)

    # Fetch paginated registry and save as aggregated JSON
    # Non-fatal: if the registry is down, Manager will fetch on first start
    print("  Fetching ComfyRegistry (paginated)...")
    try:
        nodes = fetch_registry_all()
        registry_data = json.dumps(nodes, separators=(",", ":"))
        fname = cache_filename(REGISTRY_URL)
        (CACHE_DIR / fname).write_bytes(registry_data.encode())
        print(f"  Cached {len(nodes)} registry nodes")
    except Exception as e:
        print(f"  WARNING: Registry fetch failed ({e}), skipping — Manager will fetch on first start")

    print(f"Done. {len(list(CACHE_DIR.iterdir()))} cache files written.")


if __name__ == "__main__":
    main()
