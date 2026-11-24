#!/usr/bin/env bash
# Print the sha256 of whatever a URL serves, for the staleness scraper.
#
# The scraper has to checksum release assets, which means fetching bytes. It
# does NOT need to choose where those bytes land, and `curl -o` would give it
# exactly that: an injected instruction could write .git/config (a
# core.fsmonitor command that the next `git status` executes) or a file under
# _work/_actions that a later step runs. So the download happens here, into a
# temporary file this script owns and deletes, and only the digest comes back.
set -euo pipefail

url="${1:?usage: sha256_url.sh <https-url>}"
case "$url" in
  https://*) ;;
  *)
    echo "refusing a non-https URL: ${url}" >&2
    exit 2
    ;;
esac

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl --fail --silent --show-error --location \
  --proto '=https' --tlsv1.2 --max-time 600 \
  --output "$tmp" -- "$url"

printf 'sha256: %s\n' "$(sha256sum "$tmp" | cut -d' ' -f1)"
printf 'bytes:  %s\n' "$(wc -c < "$tmp")"
printf 'url:    %s\n' "$url"
