#!/usr/bin/env python3
"""Delete Instant Clusters leaked by the cluster smoke tests.

The cluster counterpart of .github/workflows/reap-pods.yml. A cancelled CI
job can be SIGKILLed before cluster_runner's `finally` deletes its cluster,
and a leaked cluster bills every node. This only ever touches clusters named
`smoketest-<epoch>-...` (the naming from cluster_runner), and reads each
one's age from that name, so it never deletes a human's cluster.

    RUNPOD_ENV=dev RUNPOD_API_KEY=... ./reap_clusters.py
        [--max-age-minutes 90] [--delete]

Dry run unless --delete is given. Exit 1 if the cluster list cannot be read
or a delete fails — an empty listing must never pass for a clean account.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from runpod_smoke import api, config  # noqa: E402
from runpod_smoke.cluster import delete_cluster  # noqa: E402

_NAME_RE = re.compile(r"^smoketest-(\d{9,})-")

_CLUSTERS = """
query Clusters {
  myself { clusters { id name } }
}
"""


def stale_clusters(
    clusters: list[dict], now: float, max_age_sec: int,
) -> list[tuple[str, str, int]]:
    """(id, name, age_sec) for every smoke-test cluster older than the cap."""
    out = []
    for cluster in clusters:
        name = str(cluster.get("name") or "")
        match = _NAME_RE.match(name)
        if not match or not cluster.get("id"):
            continue
        age = int(now) - int(match.group(1))
        if age > max_age_sec:
            out.append((str(cluster["id"]), name, age))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-age-minutes", type=int, default=90)
    parser.add_argument("--delete", action="store_true", help="actually delete")
    args = parser.parse_args()
    if args.max_age_minutes < 1:
        print("::error::--max-age-minutes must be >= 1")
        return 1

    print(
        f"env={config.RUNPOD_ENV} ({config.GRAPHQL_URL}) "
        f"max_age={args.max_age_minutes}m delete={args.delete}"
    )
    status, data = api.graphql(_CLUSTERS, timeout=30)
    if not (200 <= status < 300) or not isinstance(data, dict):
        print(f"::error::cluster listing failed: {api.error_detail(status, data)}")
        return 1
    clusters = (data.get("myself") or {}).get("clusters")
    if not isinstance(clusters, list):
        print("::error::cluster listing returned no `clusters` list")
        return 1

    stale = stale_clusters(clusters, time.time(), args.max_age_minutes * 60)
    print(
        f"{len(clusters)} cluster(s) on the account, "
        f"{len(stale)} stale smoke-test cluster(s)"
    )
    failed = 0
    for cluster_id, name, age in stale:
        action = "deleting" if args.delete else "would delete"
        print(f"  {action} {cluster_id} {name} (age {age // 60}m)")
        if not args.delete:
            continue
        ok, detail = delete_cluster(cluster_id)
        if not ok:
            failed += 1
            print(f"::error::could not delete cluster {cluster_id}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
