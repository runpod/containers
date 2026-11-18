#!/usr/bin/env python3
"""Unit tests for latest_dev_version.newest:

    python3 .github/scripts/test_latest_dev_version.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from latest_dev_version import newest  # noqa: E402

CASES = [
    ("no tags at all", [], ""),
    ("an rc belongs to an open PR", ["2.2.0-rc.9-cuda1281-ubuntu2404"], ""),
    ("a manual -dev run has no number", ["2.2.0-dev-cuda1281-ubuntu2404"], ""),
    ("a release tag is not a dev tag", ["2.1.0-cuda1281-ubuntu2404"], ""),
    ("a cosign signature is ignored", ["sha256-ab12.sig"], ""),
    ("one dev push", ["2.2.0-dev.213-cuda1281-ubuntu2404"], "2.2.0-dev.213"),
    ("every variant of one push collapses", [
        "2.2.0-dev.213-cuda1281-ubuntu2404",
        "2.2.0-dev.213-cuda1290-ubuntu2404",
    ], "2.2.0-dev.213"),
    ("higher version wins", [
        "2.3.0-dev.220-cuda1281-ubuntu2404",
        "2.2.0-dev.999-cuda1281-ubuntu2404",
    ], "2.3.0-dev.220"),
    # A revert keeps the reverted commit in the range, so max_bump holds the
    # version and only the number moves.
    ("same version, higher PR number wins", [
        "2.3.0-dev.220-cuda1281-ubuntu2404",
        "2.3.0-dev.225-cuda1281-ubuntu2404",
    ], "2.3.0-dev.225"),
    ("10 beats 9, not lexically", [
        "2.3.0-dev.9-cuda1281-ubuntu2404",
        "2.3.0-dev.10-cuda1281-ubuntu2404",
    ], "2.3.0-dev.10"),
    ("1.10.0 beats 1.9.0", [
        "1.9.0-dev.50-ubuntu2404",
        "1.10.0-dev.20-ubuntu2404",
    ], "1.10.0-dev.20"),
    # A direct push to develop is named after its commit and cannot be
    # ordered, so a PR number at the same version wins.
    ("a PR number beats a sha at the same version", [
        "2.3.0-dev.1a2b3c4-ubuntu2404",
        "2.3.0-dev.7-ubuntu2404",
    ], "2.3.0-dev.7"),
    ("a sha still counts when nothing else does", [
        "2.3.0-dev.1a2b3c4-ubuntu2404",
    ], "2.3.0-dev.1a2b3c4"),
    ("a newer rc does not win", [
        "2.2.0-dev.213-cuda1281-ubuntu2404",
        "2.9.0-rc.400-cuda1281-ubuntu2404",
    ], "2.2.0-dev.213"),
    ("no variant suffix", ["2.2.0-dev.213"], "2.2.0-dev.213"),
]


def main() -> int:
    fails = 0
    for name, names, want in CASES:
        got = newest(names)
        if got == want:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name}: want {want!r}, got {got!r}")
            fails += 1
    if fails:
        print(f"\n{fails} test(s) failed")
        return 1
    print("\nAll latest_dev_version tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
