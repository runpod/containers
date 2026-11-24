#!/usr/bin/env python3
"""Newest `-dev.<N>` version among the tag names on stdin.

    crane ls runpod/pytorch-dev | latest_dev_version.py

Prints `X.Y.Z-dev.<N>` — the part a bake file prefixes to its variant suffix,
so every variant of one push collapses to the same answer. Prints nothing when
there is no such tag.

Only `-dev.<N>` counts: those come from a push to develop, so they are merged
code. `-rc.<N>` belongs to an open pull request and a bare `-dev` to a manual
run; neither may become a parent image.

Ordered by version and then by `<N>`, not by push time. A re-run of an older
develop commit republishes an older tag today, so "most recently pushed" would
pick up stale content; the version cannot move backwards that way. `<N>` is a
PR number, or a commit sha for a direct push to develop — a sha cannot be
ordered, so it sorts below any PR number at the same version.
"""

from __future__ import annotations

import re
import sys

TAG = re.compile(r"^(\d+)\.(\d+)\.(\d+)-dev\.([0-9A-Za-z]+)(?:-|$)")


def sort_key(match: re.Match[str]) -> tuple[int, int, int, int, int]:
    major, minor, patch, ref = match.groups()
    numbered = ref.isdigit()
    return (
        int(major), int(minor), int(patch),
        1 if numbered else 0,
        int(ref) if numbered else 0,
    )


def newest(names: list[str]) -> str:
    best: re.Match[str] | None = None
    for name in names:
        match = TAG.match(name.strip())
        if match and (best is None or sort_key(match) > sort_key(best)):
            best = match
    if best is None:
        return ""
    major, minor, patch, ref = best.groups()
    return f"{major}.{minor}.{patch}-dev.{ref}"


def main() -> int:
    print(newest(sys.stdin.read().splitlines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
