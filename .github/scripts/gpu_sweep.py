#!/usr/bin/env python3
"""Release GPU compatibility sweep: plan, report, reap.

  plan    Turn the image refs a release built into a test manifest for
          tests/test_images.py — one group per family, every GPU in
          .github/gpu-sweep.yml, `cuda_versions: allowed`.
  report  Turn the harness results JSON into the per-release compatibility
          result: image x GPU x CUDA, each pass / fail / untested.
  reap    Delete any pod this run left behind (POD_NAME_SUFFIX).

Called by .github/workflows/gpu-sweep-release.yml.

Result states. Only `pass` and `fail` are verdicts on the image:
  pass      booted and passed its checks on that GPU at that CUDA version
  fail      a pod ran and the image proved broken there
  untested  no verdict — no capacity, spend cap, GPU not offered at any
            allowed CUDA version, or a host that never answered. Never
            counts as incompatible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

# Same tag parser the harness uses to set the CUDA floor, so plan and run
# can't disagree about an image.
from runpod_smoke.instances import detect_cuda_version  # noqa: E402

SCHEMA_VERSION = 1
ASSET_NAME = "gpu-compatibility.json"
RELEASE_WORKFLOW = "release.yml"
FAMILY_TAG_RE = re.compile(r"^(?P<family>.+)-v\d+\.\d+\.\d+$")
GROUP_NAME_RE = re.compile(r"[^a-z0-9_]")
# Manifest checks a family may opt into. Each must be a boolean flag the
# harness reads per group; anything else in `checks:` is a config error.
ALLOWED_CHECKS = {
    "test_torch_packages",
    "test_ray",
    "test_comfyui",
    "test_comfyui_functional",
    "test_autoresearch",
    "test_burn",
}

STATE_RANK = {"fail": 2, "pass": 1, "untested": 0}

# Per-family image sampling (`sample:` in gpu-sweep.yml).
#   all          every image the release built (default)
#   torch-range  per CUDA build, only the oldest and newest torch variant.
#                The ends are where GPU breakage lives: old torch lacks
#                kernels for new architectures (torch 2.6 has no sm_120),
#                new torch is where regressions land. The variants between
#                them share the CUDA stack and are reported as represented.
SAMPLE_MODES = {"all", "torch-range"}
TORCH_TAG_RE = re.compile(r"-torch(?P<code>\d{3,})(?=-|$)")


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text()) or {}
    gpus = [str(g).strip() for g in cfg.get("gpus") or [] if str(g).strip()]
    if not gpus:
        raise ValueError(f"{path}: `gpus` is empty")
    if len(set(g.lower() for g in gpus)) != len(gpus):
        raise ValueError(f"{path}: `gpus` lists a GPU twice")
    for name in gpus:
        if "," in name or ":" in name:
            raise ValueError(f"{path}: GPU name {name!r} can't contain ',' or ':'")
    cap = float(cfg.get("spend_cap_usd") or 0)
    if cap <= 0:
        raise ValueError(f"{path}: `spend_cap_usd` must be > 0 — a sweep without a cap is unbounded")
    families = cfg.get("families") or {}
    for fam, body in families.items():
        body = body or {}
        bad = set(body.get("checks") or []) - ALLOWED_CHECKS
        if bad:
            raise ValueError(f"{path}: family {fam!r} has unknown checks {sorted(bad)}")
        if body.get("min_cuda") and not re.fullmatch(r"\d+\.\d+", str(body["min_cuda"])):
            raise ValueError(f"{path}: family {fam!r} min_cuda must be X.Y")
        if str(body.get("sample") or "all") not in SAMPLE_MODES:
            raise ValueError(
                f"{path}: family {fam!r} sample must be one of {sorted(SAMPLE_MODES)}"
            )
    return {
        "gpus": gpus,
        "cloud": str(cfg.get("cloud") or "ALL").upper(),
        "spend_cap_usd": cap,
        "reserve_minutes": float(cfg.get("reserve_minutes") or 30),
        "max_parallel": int(cfg.get("max_parallel") or 2),
        "catch_up_days": float(cfg.get("catch_up_days") or 3),
        "families": {fam: (body or {}) for fam, body in families.items()},
    }


def released_families(tags: list[str], graph: dict) -> dict[str, str]:
    """family -> release tag, from the tags a release run created."""
    out: dict[str, str] = {}
    for tag in tags:
        m = FAMILY_TAG_RE.match(tag.strip())
        if m and m.group("family") in graph:
            out[m.group("family")] = tag.strip()
    return out


def read_refs(refs_dir: Path) -> list[str]:
    """Every ref in every refs.json the build workflows uploaded."""
    refs: set[str] = set()
    for path in sorted(refs_dir.rglob("refs.json")):
        data = json.loads(path.read_text() or "[]")
        if not isinstance(data, list):
            raise ValueError(f"{path}: expected a JSON array of refs")
        refs.update(str(r) for r in data if r)
    return sorted(refs)


def repo_of(ref: str) -> str:
    """'docker.io/runpod/pytorch:1.4.0-cu1290-...' -> 'runpod/pytorch'."""
    name = ref.split("@", 1)[0]
    last = name.rsplit("/", 1)[-1]
    if ":" in last:
        name = name[: len(name) - len(last)] + last.split(":", 1)[0]
    for prefix in ("docker.io/", "index.docker.io/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def torch_version(ref: str) -> tuple[int, ...] | None:
    """'...-cu1300-torch2121-...' -> (2, 12, 1); None without a torch tag.
    The code is major, minor, patch with the minor taking the middle digits:
    torch280 is 2.8.0, torch2130 is 2.13.0."""
    m = TORCH_TAG_RE.search(ref)
    if not m:
        return None
    code = m.group("code")
    return (int(code[0]), int(code[1:-1]), int(code[-1]))


def sample_torch_range(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the oldest and newest torch variant of each image that differs
    only in its torch version (same family, CUDA build, OS). Returns
    (kept, dropped); each dropped entry names the images representing it."""
    groups: dict[tuple[str, str], list[dict]] = {}
    kept: list[dict] = []
    for item in items:
        if torch_version(item["image"]) is None:
            kept.append(item)
            continue
        key = (item["family"], TORCH_TAG_RE.sub("-torch*", item["image"]))
        groups.setdefault(key, []).append(item)
    dropped: list[dict] = []
    for members in groups.values():
        members.sort(key=lambda i: torch_version(i["image"]))
        ends = [members[0]] if len(members) == 1 else [members[0], members[-1]]
        kept.extend(ends)
        for item in members[1:-1]:
            dropped.append({
                "image": item["image"],
                "reason": "sampled out (torch-range): same CUDA build as the oldest and newest torch variants, which were tested",
                "represented_by": [e["image"] for e in ends],
            })
    order = {item["image"]: n for n, item in enumerate(items)}
    kept.sort(key=lambda i: order[i["image"]])
    return kept, dropped


def plan(
    cfg: dict, graph: dict, released: dict[str, str], refs: list[str], commit: str = "",
) -> dict:
    """Pick the images to sweep and say why the rest were left out."""
    repo_to_family = {
        body.get("image_repo"): fam for fam, body in graph.items() if body.get("image_repo")
    }
    images: list[dict] = []
    skipped: list[dict] = []
    for ref in refs:
        family = repo_to_family.get(repo_of(ref))
        if family is None:
            skipped.append({"image": ref, "reason": "repo is not in families.yml"})
            continue
        if family not in released:
            skipped.append({"image": ref, "reason": f"{family} was not released by this run, or that release already has a result"})
            continue
        if family not in cfg["families"]:
            skipped.append({"image": ref, "reason": f"{family} is not in the sweep config"})
            continue
        fam_cfg = cfg["families"][family]
        floor = detect_cuda_version(ref) or fam_cfg.get("min_cuda")
        if not floor:
            skipped.append({"image": ref, "reason": "no CUDA floor (CPU or ROCm image)"})
            continue
        images.append({
            "image": ref,
            "family": family,
            "release_tag": released[family],
            "commit": commit,
            "cuda_floor": str(floor),
        })
    sampled = [i for i in images if cfg["families"][i["family"]].get("sample") == "torch-range"]
    if sampled:
        kept, dropped = sample_torch_range(sampled)
        keep = {i["image"] for i in kept}
        images = [i for i in images if i["image"] in keep or i not in sampled]
        skipped.extend(dropped)
    return {"images": images, "skipped": skipped}


def render_manifest(cfg: dict, images: list[dict]) -> str:
    """Manifest in tests/runpod_smoke/manifest.py's fixed format: one group
    per family, since checks and the fallback floor are per family."""
    by_family: dict[str, list[str]] = {}
    for item in images:
        by_family.setdefault(item["family"], []).append(item["image"])
    lines: list[str] = []
    for family, refs in by_family.items():
        fam_cfg = cfg["families"][family]
        lines.append(f"sweep_{GROUP_NAME_RE.sub('_', family.lower())}:")
        lines.append("    images:")
        lines.extend(f"    - {ref}" for ref in refs)
        # instances + check_all_gpu = one job per named GPU, not a fallback
        # chain (test_images._build_jobs).
        lines.append("    instances:")
        lines.extend(f"    - {gpu}" for gpu in cfg["gpus"])
        lines.append("    check_all_gpu: true")
        lines.append("    cuda_versions: allowed")
        if fam_cfg.get("min_cuda"):
            lines.append(f'    min_cuda_version: "{fam_cfg["min_cuda"]}"')
        for check in fam_cfg.get("checks") or []:
            lines.append(f"    {check}: true")
    return "\n".join(lines) + "\n"


def plan_releases(
    cfg: dict, graph: dict, releases: list[dict], refs_root: Path,
) -> tuple[dict[str, str], dict]:
    """plan() for each release run in releases.json, merged. Returns
    (tag -> family, plan). A run whose refs artifacts are gone is listed as
    skipped per tag, never silently dropped."""
    tags_out: dict[str, str] = {}
    images: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for rel in releases:
        released = released_families(rel.get("tags") or [], graph)
        run_dir = refs_root / str(rel.get("run_id") or "")
        refs = read_refs(run_dir) if rel.get("run_id") and run_dir.exists() else []
        if not refs:
            for tag in released.values():
                skipped.append({
                    "image": tag,
                    "reason": rel.get("note") or (
                        f"no refs from release run {rel.get('run_id')} "
                        "(artifacts are kept 3 days) — not swept"
                    ),
                })
            continue
        tags_out.update({tag: fam for fam, tag in released.items()})
        result = plan(cfg, graph, released, refs, rel.get("sha") or "")
        for item in result["images"]:
            if item["image"] not in seen:
                seen.add(item["image"])
                images.append(item)
        skipped.extend(result["skipped"])
    return tags_out, {"images": images, "skipped": skipped}


def cmd_plan(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    graph = (yaml.safe_load(args.graph.read_text()) or {}).get("families") or {}
    unknown = sorted(set(cfg["families"]) - set(graph))
    if unknown:
        print(f"::error::sweep config names families not in {args.graph}: {unknown}")
        return 1
    releases = json.loads(args.releases.read_text()) if args.releases.exists() else []
    released, result = plan_releases(cfg, graph, releases, args.refs_root)
    print(f"released tags: {', '.join(sorted(released)) or 'none'}")
    for item in result["images"]:
        print(f"  sweep  {item['image']}  (floor CUDA {item['cuda_floor']})")
    for item in result["skipped"]:
        print(f"  skip   {item['image']}  — {item['reason']}")

    out = {
        "config": cfg,
        "released": released,
        **result,
    }
    args.plan_out.write_text(json.dumps(out, indent=2) + "\n")
    if result["images"]:
        args.manifest_out.write_text(render_manifest(cfg, result["images"]))
    _set_output("images", str(len(result["images"])))
    _set_output("cloud", cfg["cloud"])
    _set_output("max-parallel", str(cfg["max_parallel"]))
    _set_output("spend-cap-usd", f"{cfg['spend_cap_usd']:g}")
    _set_output("reserve-minutes", f"{cfg['reserve_minutes']:g}")
    # Every image x GPU x up to ~4 CUDA versions x 2 tiers before dedupe —
    # the spend cap is the real limit, so this cap must never bind first.
    _set_output(
        "max-combos",
        str(max(120, len(result["images"]) * len(cfg["gpus"]) * 8)),
    )
    return 0


def catch_up_candidates(
    tags: list[dict], families: dict, *, sha: str, now: float, days: float,
) -> list[dict]:
    """Release tags of swept `families` behind `sha` (not at it), created in
    the last `days`: the releases a cancelled pending sweep may have skipped.
    Older ones can't be swept anyway — their refs artifacts are gone."""
    out = []
    for t in tags:
        m = FAMILY_TAG_RE.match(t["tag"])
        if not m or m.group("family") not in families:
            continue
        if t["commit"] == sha or t["date"] < now - days * 86400:
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t["date"], t["tag"]))


def _gh_api(path: str) -> dict | None:
    """GET a GitHub API path with gh; None on 404."""
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode != 0:
        if "HTTP 404" in proc.stderr:
            return None
        raise RuntimeError(f"gh api {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "null")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _merged_tags(sha: str) -> list[dict]:
    fmt = "%(refname:short)%09%(objectname)%09%(*objectname)%09%(creatordate:unix)"
    out = []
    for line in _git("for-each-ref", "--merged", sha, f"--format={fmt}", "refs/tags").splitlines():
        tag, obj, peeled, date = line.split("\t")
        out.append({"tag": tag, "commit": peeled or obj, "date": float(date or 0)})
    return out


def _has_result(repo: str, tag: str) -> bool | None:
    """True if the tag's Release has the sweep asset, False if not, None if
    there is no Release (the family wasn't released)."""
    rel = _gh_api(f"repos/{repo}/releases/tags/{tag}")
    if rel is None:
        return None
    return any(a.get("name") == ASSET_NAME for a in rel.get("assets") or [])


def _release_run_for(repo: str, commit: str) -> int | None:
    data = _gh_api(
        f"repos/{repo}/actions/workflows/{RELEASE_WORKFLOW}/runs"
        f"?head_sha={commit}&event=push&status=completed&per_page=10"
    ) or {}
    runs = sorted(data.get("workflow_runs") or [], key=lambda r: r["id"], reverse=True)
    return runs[0]["id"] if runs else None


def cmd_releases(args: argparse.Namespace) -> int:
    """Write the release runs this sweep covers: the triggering run, plus
    recent releases behind it with no result yet. The workflow keeps one
    concurrency group, so only one sweep spends at a time, and GitHub keeps
    one pending run — a release whose sweep was dropped from the queue is
    picked up here by the next one."""
    cfg = load_config(args.config)
    graph = (yaml.safe_load(args.graph.read_text()) or {}).get("families") or {}
    repo = os.environ["GH_REPO"]

    def is_family(tag: str) -> bool:
        m = FAMILY_TAG_RE.match(tag)
        return bool(m and m.group("family") in graph)

    releases: list[dict] = []
    current = [t for t in _git("tag", "--points-at", args.sha).split() if is_family(t)]
    # A dispatch is an explicit re-sweep. On workflow_run, a release an
    # earlier sweep already caught up on is not swept twice.
    todo = [t for t in current if args.force or _has_result(repo, t) is not True]
    for tag in sorted(set(current) - set(todo)):
        print(f"  done   {tag} (already has {ASSET_NAME})")
    if todo:
        releases.append({"run_id": args.run_id, "sha": args.sha, "tags": todo, "catch_up": False})

    by_commit: dict[str, list[str]] = {}
    candidates = catch_up_candidates(
        _merged_tags(args.sha), cfg["families"], sha=args.sha, now=time.time(), days=cfg["catch_up_days"],
    )
    for t in candidates:
        if _has_result(repo, t["tag"]) is False:
            by_commit.setdefault(t["commit"], []).append(t["tag"])
    for commit, tags in by_commit.items():
        run_id = _release_run_for(repo, commit)
        rel = {"run_id": run_id, "sha": commit, "tags": tags, "catch_up": True}
        if run_id is None:
            rel["note"] = f"no completed '{RELEASE_WORKFLOW}' push run found for {commit[:12]} — not swept"
        releases.append(rel)

    for rel in releases:
        kind = "catch-up" if rel["catch_up"] else "release"
        print(f"  {kind:8} run {rel['run_id']} @ {rel['sha'][:12]}: {' '.join(rel['tags'])}")
    args.out.write_text(json.dumps(releases, indent=2) + "\n")
    _set_output("count", str(sum(len(r["tags"]) for r in releases)))
    _set_output("run-ids", " ".join(str(r["run_id"]) for r in releases if r["run_id"]))
    return 0


def _set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def untested_reason(note: str) -> str:
    """Coarse category for an untested cell, so consumers can filter without
    parsing harness prose."""
    n = (note or "").lower()
    if "spend cap" in n:
        return "spend_cap"
    if "below the image's cuda floor" in n:
        return "below_cuda_floor"
    if "not offered" in n or "not in the gpu catalog" in n:
        return "not_offered"
    if "never answered" in n or "never assigned an ssh endpoint" in n:
        return "host_unresponsive"
    if "no capacity" in n or "none had capacity" in n or "no cuda versions" in n:
        return "no_capacity"
    return "other"


def _cell_state(status: str) -> str:
    return {"PASS": "pass", "FAIL": "fail"}.get(status, "untested")


def build_report(
    plan_data: dict, results: dict, *, run_url: str, log_url: str, commit: str,
) -> dict:
    cfg = plan_data["config"]
    gpu_order = cfg["gpus"]
    rows = results.get("results") or []

    # Display name -> catalog id, from whatever rows carried one.
    gpu_ids: dict[str, str] = {}
    for r in rows:
        if r.get("instance") and r.get("gpu_id"):
            gpu_ids[r["instance"].lower()] = r["gpu_id"]

    images_out = []
    for item in plan_data["images"]:
        image = item["image"]
        cells: dict[tuple[str, str], dict] = {}
        for r in rows:
            if r.get("image") != image:
                continue
            gpu = r.get("instance") or ""
            match = next((g for g in gpu_order if g.lower() == gpu.lower()), None)
            if match is None:
                continue
            cuda = r.get("requested_cuda") or r.get("cuda") or ""
            state = _cell_state(r.get("status", ""))
            cell = {
                "gpu_name": match,
                "gpu_id": gpu_ids.get(match.lower(), ""),
                "cuda_version": cuda or None,
                "state": state,
                "cloud": r.get("cloud") or None,
                "reason": (r.get("note") or None) if state != "pass" else None,
                "untested_reason": untested_reason(r.get("note", "")) if state == "untested" else None,
                "log_url": log_url,
            }
            key = (match, cuda)
            prev = cells.get(key)
            # Tiers are deduplicated, so a cell has one verdict at most; if
            # two still meet, the stronger claim wins and FAIL outranks PASS.
            # Between two untested rows, "not offered in this tier" loses to
            # whatever the other tier said: the GPU exists there, so its
            # reason (usually no capacity) is the one worth reporting.
            if (
                prev is None
                or STATE_RANK[state] > STATE_RANK[prev["state"]]
                or (
                    state == prev["state"] == "untested"
                    and prev["untested_reason"] == "not_offered"
                    and cell["untested_reason"] != "not_offered"
                )
            ):
                cells[key] = cell

        # A GPU with any per-version cell doesn't need its "no version
        # testable" placeholder; a GPU with no row at all is still listed,
        # so a missing GPU reads as untested rather than vanishing.
        for gpu in gpu_order:
            versioned = [k for k in cells if k[0] == gpu and k[1]]
            if versioned:
                cells.pop((gpu, ""), None)
            elif (gpu, "") not in cells:
                cells[(gpu, "")] = {
                    "gpu_name": gpu,
                    "gpu_id": gpu_ids.get(gpu.lower(), ""),
                    "cuda_version": None,
                    "state": "untested",
                    "cloud": None,
                    "reason": "no result row — not planned (MAX_CUDA_COMBOS?) or the run was cut short",
                    "untested_reason": "other",
                    "log_url": log_url,
                }

        def sort_key(cell: dict) -> tuple:
            v = cell["cuda_version"] or "0.0"
            return (
                gpu_order.index(cell["gpu_name"]),
                [-int(p) for p in v.split(".") if p.isdigit()],
            )

        ordered = sorted(cells.values(), key=sort_key)
        by_gpu: dict[str, dict[str, list[str]]] = {}
        for cell in ordered:
            ident = cell["gpu_id"] or cell["gpu_name"]
            bucket = by_gpu.setdefault(ident, {"pass": [], "fail": [], "untested": []})
            bucket[cell["state"]].append(cell["cuda_version"] or "-")
        images_out.append({
            **item,
            "results": ordered,
            # Derived for template.yaml. Untested never feeds either list:
            # incompatible needs a FAIL and no PASS on any allowed version,
            # recommended needs a PASS and no FAIL. A GPU with both is
            # CUDA-version dependent and left for a human (partial).
            "incompatible_gpu_ids": sorted(g for g, b in by_gpu.items() if b["fail"] and not b["pass"]),
            "recommended_gpu_ids": sorted(g for g, b in by_gpu.items() if b["pass"] and not b["fail"]),
            "partial_gpu_ids": sorted(g for g, b in by_gpu.items() if b["pass"] and b["fail"]),
        })

    totals = {"pass": 0, "fail": 0, "untested": 0}
    for img in images_out:
        for cell in img["results"]:
            totals[cell["state"]] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "run_url": run_url,
        "gpus": [{"name": g, "id": gpu_ids.get(g.lower(), "")} for g in gpu_order],
        "spend": results.get("spend"),
        "totals": totals,
        "images": images_out,
        "skipped_images": plan_data.get("skipped", []),
    }


def render_markdown(report: dict) -> str:
    icon = {"pass": "✅", "fail": "❌", "untested": "·"}
    out = ["## Release GPU compatibility sweep", ""]
    t = report["totals"]
    spend = report.get("spend") or {}
    out.append(
        f"{t['pass']} pass, {t['fail']} fail, {t['untested']} untested"
        + (f" · spend ~${spend.get('spent_usd', 0):.2f} of ${spend.get('cap_usd', 0):.2f} cap" if spend else "")
    )
    out.append("")
    out.append("Untested = no capacity, spend cap, or not offered — never incompatible.")
    gpus = [g["name"] for g in report["gpus"]]
    for img in report["images"]:
        out += ["", f"### `{img['image']}`", ""]
        out.append("| GPU | Host CUDA → result |")
        out.append("| --- | --- |")
        for gpu in gpus:
            cells = [c for c in img["results"] if c["gpu_name"] == gpu]
            parts = []
            for c in cells:
                label = c["cuda_version"] or "any"
                parts.append(f"{icon[c['state']]} {label}")
            out.append(f"| {gpu} | {' '.join(parts)} |")
        fails = [c for c in img["results"] if c["state"] == "fail"]
        for c in fails:
            reason = (c["reason"] or "").replace("|", "\\|")[:200]
            out.append(f"\n- ❌ {c['gpu_name']} @ CUDA {c['cuda_version'] or '?'}: {reason}")
    return "\n".join(out) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    plan_data = json.loads(args.plan.read_text())
    results = json.loads(args.results.read_text()) if args.results.exists() else {}
    if not results.get("results"):
        print(
            f"::error::no harness results in {args.results} — the sweep did not "
            "run, so no report is written or attached"
        )
        return 1
    report = build_report(
        plan_data, results, run_url=args.run_url, log_url=args.log_url or args.run_url,
        commit=args.commit,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "gpu-compatibility.json").write_text(json.dumps(report, indent=2) + "\n")
    # One file per release tag, attached to that tag's GitHub Release: its
    # own images only, same schema. A catch-up sweep covers several
    # releases, so the commit is the tag's, not the run's.
    for tag in plan_data.get("released", {}):
        imgs = [i for i in report["images"] if i.get("release_tag") == tag]
        if not imgs:
            continue
        sub = {**report, "images": imgs, "release_tag": tag}
        sub["commit"] = imgs[0].get("commit") or report["commit"]
        sub["totals"] = {
            s: sum(1 for i in imgs for c in i["results"] if c["state"] == s)
            for s in ("pass", "fail", "untested")
        }
        sub.pop("skipped_images", None)
        (args.out_dir / f"{tag}.json").write_text(json.dumps(sub, indent=2) + "\n")

    md = render_markdown(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    else:
        print(md)
    for img in report["images"]:
        for c in img["results"]:
            if c["state"] == "fail":
                print(
                    f"::warning::GPU sweep: {img['image']} failed on "
                    f"{c['gpu_name']} at CUDA {c['cuda_version'] or '?'} — {c['reason']}"
                )
    _set_output("fail-count", str(report["totals"]["fail"]))
    return 0


# ---------------------------------------------------------------------------
# reap
# ---------------------------------------------------------------------------


SWEEP_POD_RE = re.compile(r"^smoketest-\d+-.*-sweep\d+$")


def is_sweep_pod(name: str, suffix: str = "") -> bool:
    """`suffix` set: that run's pods only. Empty: any sweep run's pods."""
    if suffix:
        return name.startswith("smoketest-") and name.endswith(f"-{suffix}")
    return bool(SWEEP_POD_RE.match(name))


def cmd_reap(args: argparse.Namespace) -> int:
    """Delete every pod whose name ends with -<suffix>, or with --any-sweep
    every sweep pod of any run. The harness deletes its pods itself; this
    catches what a cancelled job left. --any-sweep runs first thing in a
    sweep: sweeps share one concurrency group, so a sweep pod alive then
    belongs to a runner that died and will never settle or reap it."""
    from runpod_smoke import api

    suffix = args.suffix or ""
    if args.any_sweep == bool(suffix):
        print("::error::pass exactly one of --suffix or --any-sweep")
        return 1
    if suffix and not (suffix.isascii() and suffix.isalnum()):
        print(f"::error::suffix must be alphanumeric, got {suffix!r}")
        return 1
    status, data = api.request_with_retries("GET", "/pods", timeout=30)
    if not (200 <= status < 300):
        print(f"::error::could not list pods: {api.error_detail(status, data)}")
        return 1
    pods = data if isinstance(data, list) else (data or {}).get("pods") or []
    mine = [p for p in pods if isinstance(p, dict) and is_sweep_pod(str(p.get("name", "")), suffix)]
    failed = 0
    for pod in mine:
        st, body = api.request_with_retries("DELETE", f"/pods/{pod['id']}", timeout=30)
        if 200 <= st < 300 or st == 404:
            print(f"deleted leftover pod {pod['name']} ({pod['id']})")
        else:
            failed += 1
            print(f"::warning::could not delete {pod['name']} ({pod['id']}): {api.error_detail(st, body)}")
    print(f"leftover sweep pods: {len(mine)} found, {len(mine) - failed} deleted")
    if failed:
        print(f"::error::{failed} sweep pod(s) still running — reap-pods.yml will retry hourly")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--config", type=Path, default=REPO_ROOT / ".github/gpu-sweep.yml")
    p.add_argument("--graph", type=Path, default=REPO_ROOT / ".github/families.yml")
    p.add_argument("--releases", type=Path, required=True, help="releases.json from `releases`")
    p.add_argument("--refs-root", type=Path, required=True, help="<root>/<run id>/**/refs.json")
    p.add_argument("--manifest-out", type=Path, required=True)
    p.add_argument("--plan-out", type=Path, required=True)
    p.set_defaults(func=cmd_plan)

    r = sub.add_parser("report")
    r.add_argument("--plan", type=Path, required=True)
    r.add_argument("--results", type=Path, required=True)
    r.add_argument("--out-dir", type=Path, required=True)
    r.add_argument("--run-url", default="")
    r.add_argument("--log-url", default="")
    r.add_argument("--commit", default="")
    r.set_defaults(func=cmd_report)

    c = sub.add_parser("releases")
    c.add_argument("--config", type=Path, default=REPO_ROOT / ".github/gpu-sweep.yml")
    c.add_argument("--graph", type=Path, default=REPO_ROOT / ".github/families.yml")
    c.add_argument("--sha", required=True)
    c.add_argument("--run-id", type=int, required=True)
    c.add_argument("--force", action="store_true", help="sweep the run's own tags even if they have a result")
    c.add_argument("--out", type=Path, required=True)
    c.set_defaults(func=cmd_releases)

    k = sub.add_parser("reap")
    k.add_argument("--suffix", default="")
    k.add_argument("--any-sweep", action="store_true")
    k.set_defaults(func=cmd_reap)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"::error::{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
