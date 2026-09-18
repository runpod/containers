#!/usr/bin/env python3
"""Turn a list of changed files into the template families to build, in order.

A family is selected when one of its `paths` changed. Every family that
depends on a selected one comes along after it: a new base image means a new
pytorch image, and a new pytorch image means a new pytorch-cluster. The graph
lives in .github/families.yml.

    plan_families.py --changed-files changed.txt
    git diff --name-only HEAD~1..HEAD | plan_families.py --changed-files -
    plan_families.py --all                 # workflow_dispatch: no diff to read
    plan_families.py --workflows           # build workflows to call, not families
    plan_families.py --image-repo comfyui  # just read one field of the graph

Prints a JSON array in build order on stdout and a human summary on stderr.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH = REPO_ROOT / ".github" / "families.yml"


class GraphError(Exception):
    """The graph file is unusable — a typo we must not paper over."""


def load_graph(path: Path) -> dict[str, dict]:
    raw = yaml.safe_load(path.read_text()) or {}
    families = raw.get("families")
    if not isinstance(families, dict) or not families:
        raise GraphError(f"{path}: no 'families' mapping")

    graph: dict[str, dict] = {}
    for name, spec in families.items():
        spec = spec or {}
        paths = spec.get("paths") or []
        deps = spec.get("depends_on") or []
        if not isinstance(paths, list) or not paths:
            raise GraphError(f"{path}: family '{name}' has no paths")
        if not isinstance(deps, list):
            raise GraphError(f"{path}: family '{name}' has a malformed depends_on")
        graph[name] = {
            "paths": list(paths),
            "depends_on": list(deps),
            "image_repo": spec.get("image_repo") or "",
            "workflow": spec.get("workflow") or "",
        }

    for name, spec in graph.items():
        for dep in spec["depends_on"]:
            if dep not in graph:
                raise GraphError(f"{path}: '{name}' depends on unknown family '{dep}'")
            if dep == name:
                raise GraphError(f"{path}: '{name}' depends on itself")
    return graph


def _matches(pattern: str, changed: str) -> bool:
    # A trailing /** means "this directory and everything under it". fnmatch's
    # '*' happily crosses '/', so a prefix test is both cheaper and clearer.
    if pattern.endswith("/**"):
        return changed.startswith(pattern[:-2])
    return fnmatch.fnmatch(changed, pattern)


def direct_matches(graph: dict[str, dict], changed: list[str]) -> set[str]:
    return {
        name
        for name, spec in graph.items()
        if any(_matches(p, c) for p in spec["paths"] for c in changed)
    }


def with_dependents(graph: dict[str, dict], selected: set[str]) -> set[str]:
    """Add every family that builds FROM a selected one, transitively."""
    out = set(selected)
    while True:
        extra = {
            name
            for name, spec in graph.items()
            if name not in out and out.intersection(spec["depends_on"])
        }
        if not extra:
            return out
        out |= extra


def build_order(graph: dict[str, dict], selected: set[str]) -> list[str]:
    """Declaration order, except a family never precedes what it builds FROM.

    Only dependencies inside the selected set constrain the order — the rest
    are already published, so there is nothing to wait for.
    """
    remaining = [n for n in graph if n in selected]
    ordered: list[str] = []
    while remaining:
        ready = [
            n
            for n in remaining
            if all(d in ordered or d not in selected for d in graph[n]["depends_on"])
        ]
        if not ready:
            raise GraphError(f"dependency cycle among {', '.join(sorted(remaining))}")
        ordered.extend(ready)
        remaining = [n for n in remaining if n not in ready]
    return ordered


def plan(graph: dict[str, dict], changed: list[str], all_families: bool) -> list[str]:
    selected = set(graph) if all_families else with_dependents(
        graph, direct_matches(graph, changed)
    )
    return build_order(graph, selected)


def _read_changed(source: str) -> list[str]:
    text = sys.stdin.read() if source == "-" else Path(source).read_text()
    return [line.strip() for line in text.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    ap.add_argument(
        "--changed-files",
        help="file with one changed path per line, or '-' for stdin",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="select every family (no diff available)",
    )
    ap.add_argument(
        "--workflows",
        action="store_true",
        help="print the reusable build workflows covering the planned families",
    )
    ap.add_argument(
        "--image-repo",
        metavar="FAMILY",
        help="print the Docker Hub repo this family publishes to, then exit",
    )
    args = ap.parse_args()

    if not (args.all or args.changed_files or args.image_repo):
        ap.error("pass --changed-files, --all or --image-repo")

    try:
        graph = load_graph(args.graph)
        if args.image_repo:
            if args.image_repo not in graph:
                raise GraphError(f"unknown family '{args.image_repo}'")
            print(graph[args.image_repo]["image_repo"])
            return 0
        changed = [] if args.all else _read_changed(args.changed_files)
        families = plan(graph, changed, args.all)
        if args.workflows:
            # Deduplicated, first-needed first: base covers four families.
            workflows = list(dict.fromkeys(graph[f]["workflow"] for f in families))
            print(f"workflows:       {', '.join(workflows) or 'none'}", file=sys.stderr)
            print(json.dumps(workflows))
            return 0
    except GraphError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    if args.all:
        print("changed sources: every family (no diff to read)", file=sys.stderr)
    else:
        direct = sorted(direct_matches(graph, changed))
        print(f"changed files:   {len(changed)}", file=sys.stderr)
        print(f"changed sources: {', '.join(direct) or 'none'}", file=sys.stderr)
    print(f"build order:     {', '.join(families) or 'none'}", file=sys.stderr)
    print(json.dumps(families))
    return 0


if __name__ == "__main__":
    sys.exit(main())
