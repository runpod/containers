#!/usr/bin/env python3
"""Release notes for one family.

    release_notes.py <family> <previous-version> <tag> [pathspec...]

One section per commit that touched the family since its previous release: a
release can carry several changes — work from a run that failed, or one
GitHub dropped from the queue — and the newest squash description alone would
describe the wrong one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys


TRAILER = re.compile(r"^(co-authored-by|signed-off-by):", re.IGNORECASE)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git",) + args, check=True, capture_output=True, text=True
    ).stdout


def commits_touching(rev_range: str, paths: list[str]) -> list[str]:
    out = _git("log", "--format=%H", rev_range, "--", *paths)
    return [line for line in out.splitlines() if line]


def _description(sha: str) -> str:
    body = _git("log", "-1", "--format=%b", sha).splitlines()
    return "\n".join(line for line in body if not TRAILER.match(line)).strip()


def notes(family: str, previous: str, tag: str, paths: list[str]) -> str:
    # A first release has no earlier tag to walk back to.
    rev_range = f"{family}-v{previous}..HEAD" if previous else "HEAD~1..HEAD"

    sections = []
    for sha in commits_touching(rev_range, paths):
        section = "### " + _git("log", "-1", "--format=%s", sha).strip()
        description = _description(sha)
        sections.append(f"{section}\n\n{description}" if description else section)

    if previous:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "runpod/containers")
        sections.append(
            f"**Full Changelog**: {server}/{repo}/compare/"
            f"{family}-v{previous}...{tag}"
        )
    return "\n\n".join(sections) + "\n" if sections else ""


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    family, previous, tag, *paths = sys.argv[1:]
    sys.stdout.write(notes(family, previous, tag, paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
