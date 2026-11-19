#!/usr/bin/env python3
"""Unit tests for gpu_sweep.py — plan and report, no network.

    python3 .github/scripts/test_gpu_sweep.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tests"))

import gpu_sweep as S  # noqa: E402
from runpod_smoke.manifest import parse_manifest  # noqa: E402

GRAPH = {
    "base": {"image_repo": "runpod/base"},
    "pytorch": {"image_repo": "runpod/pytorch"},
    "nvidia-pytorch": {"image_repo": "runpod/nvidia-pytorch"},
    "rocm": {"image_repo": "runpod/rocm"},
    "comfyui": {"image_repo": "runpod/comfyui"},
}

CFG = {
    "gpus": ["RTX 5080", "B200"],
    "cloud": "ALL",
    "spend_cap_usd": 50.0,
    "reserve_minutes": 30.0,
    "max_parallel": 4,
    "families": {
        "base": {},
        "pytorch": {"checks": ["test_torch_packages"]},
        "nvidia-pytorch": {"min_cuda": "13.0"},
        "rocm": {},
    },
}

PT = "docker.io/runpod/pytorch:1.4.0-cu1300-torch290-ubuntu2404"
BASE_GPU = "runpod/base:1.2.0-cuda1281-ubuntu2404"
BASE_CPU = "runpod/base:1.2.0-ubuntu2404"
NGC = "runpod/nvidia-pytorch:1.1.0-25.11"
ROCM = "runpod/rocm:1.0.0-rocm644-ubuntu2404"
COMFY = "runpod/comfyui:1.0.0-comfyui0.3-cuda13.0"


class Plan(unittest.TestCase):
    def test_repo_of(self):
        self.assertEqual(S.repo_of(PT), "runpod/pytorch")
        self.assertEqual(S.repo_of("localhost:5000/runpod/x:tag"), "localhost:5000/runpod/x")
        self.assertEqual(S.repo_of("runpod/x@sha256:abc"), "runpod/x")

    def test_released_families_from_tags(self):
        tags = ["pytorch-v1.4.0", "nvidia-pytorch-v1.1.0", "v0.9.0", "notafamily-v1.0.0"]
        self.assertEqual(
            S.released_families(tags, GRAPH),
            {"pytorch": "pytorch-v1.4.0", "nvidia-pytorch": "nvidia-pytorch-v1.1.0"},
        )

    def test_selection(self):
        released = {f: f"{f}-v1.0.0" for f in ("base", "pytorch", "nvidia-pytorch", "rocm")}
        out = S.plan(CFG, GRAPH, released, [PT, BASE_GPU, BASE_CPU, NGC, ROCM, COMFY])
        picked = {i["image"]: i["cuda_floor"] for i in out["images"]}
        self.assertEqual(picked, {PT: "13.0", BASE_GPU: "12.8", NGC: "13.0"})
        reasons = {s["image"]: s["reason"] for s in out["skipped"]}
        self.assertIn("no CUDA floor", reasons[BASE_CPU])
        self.assertIn("no CUDA floor", reasons[ROCM])
        self.assertIn("not released", reasons[COMFY])

    def test_manifest_round_trips_through_the_harness_parser(self):
        released = {"pytorch": "pytorch-v1.4.0", "nvidia-pytorch": "nvidia-pytorch-v1.1.0"}
        images = S.plan(CFG, GRAPH, released, [PT, NGC])["images"]
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(S.render_manifest(CFG, images))
        manifest = parse_manifest(Path(fh.name))
        self.assertEqual(manifest["sweep_pytorch"]["images"], [PT])
        self.assertEqual(manifest["sweep_pytorch"]["instances"], ["RTX 5080", "B200"])
        self.assertIs(manifest["sweep_pytorch"]["check_all_gpu"], True)
        self.assertEqual(manifest["sweep_pytorch"]["cuda_versions"], "allowed")
        self.assertIs(manifest["sweep_pytorch"]["test_torch_packages"], True)
        self.assertEqual(manifest["sweep_nvidia_pytorch"]["min_cuda_version"], "13.0")

    def test_torch_version_parsing(self):
        self.assertEqual(S.torch_version("runpod/pytorch:2.0.0-cu1300-torch2121-ubuntu2404"), (2, 12, 1))
        self.assertEqual(S.torch_version("runpod/pytorch:2.0.0-cu1300-torch280-ubuntu2404"), (2, 8, 0))
        self.assertEqual(S.torch_version("runpod/pytorch:2.0.0-cu1300-torch2130-ubuntu2404"), (2, 13, 0))
        self.assertIsNone(S.torch_version(BASE_GPU))

    def test_torch_range_keeps_oldest_and_newest_per_cuda(self):
        cfg = {**CFG, "families": {**CFG["families"], "pytorch": {"sample": "torch-range"}}}
        refs = [
            f"runpod/pytorch:2.0.0-cu{cu}-torch{t}-ubuntu2404"
            for cu in ("1281", "1300")
            for t in ("260", "280", "2121", "291")
        ] + ["runpod/pytorch:2.0.0-cu1320-torch2130-ubuntu2404", BASE_GPU]
        out = S.plan(cfg, GRAPH, {"pytorch": "pytorch-v2.0.0", "base": "base-v2.0.0"}, refs)
        picked = sorted(i["image"].split(":")[1] for i in out["images"])
        self.assertEqual(picked, sorted([
            "2.0.0-cu1281-torch260-ubuntu2404", "2.0.0-cu1281-torch2121-ubuntu2404",
            "2.0.0-cu1300-torch260-ubuntu2404", "2.0.0-cu1300-torch2121-ubuntu2404",
            # a lone variant is its own range
            "2.0.0-cu1320-torch2130-ubuntu2404",
            # families without `sample` are untouched
            "1.2.0-cuda1281-ubuntu2404",
        ]))
        dropped = {s["image"]: s for s in out["skipped"] if "represented_by" in s}
        self.assertEqual(len(dropped), 4)
        rep = dropped["runpod/pytorch:2.0.0-cu1300-torch280-ubuntu2404"]["represented_by"]
        self.assertEqual(rep, [
            "runpod/pytorch:2.0.0-cu1300-torch260-ubuntu2404",
            "runpod/pytorch:2.0.0-cu1300-torch2121-ubuntu2404",
        ])

    def test_config_rejects_unknown_sample_mode(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write("gpus: [B200]\nspend_cap_usd: 5\nfamilies:\n  pytorch:\n    sample: newest\n")
        with self.assertRaisesRegex(ValueError, "sample must be one of"):
            S.load_config(Path(fh.name))

    def test_config_requires_a_cap(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write("gpus: [B200]\nfamilies: {}\n")
        with self.assertRaisesRegex(ValueError, "spend_cap_usd"):
            S.load_config(Path(fh.name))

    def test_config_rejects_unknown_check(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write("gpus: [B200]\nspend_cap_usd: 5\nfamilies:\n  pytorch:\n    checks: [test_pip_check]\n")
        with self.assertRaisesRegex(ValueError, "unknown checks"):
            S.load_config(Path(fh.name))

    def test_shipped_config_is_valid(self):
        cfg = S.load_config(HERE.parent / "gpu-sweep.yml")
        import yaml
        graph = yaml.safe_load((HERE.parent / "families.yml").read_text())["families"]
        self.assertFalse(set(cfg["families"]) - set(graph))


def _row(image, status, gpu, cuda, note="", cloud="SECURE", gpu_id=""):
    return {
        "image": image, "status": status, "instance": gpu, "gpu_id": gpu_id,
        "cloud": cloud, "cuda": cuda if status in ("PASS", "FAIL") else "",
        "requested_cuda": cuda, "note": note,
    }


class Report(unittest.TestCase):
    def _report(self, rows):
        plan = {
            "config": CFG,
            "released": {"pytorch-v1.4.0": "pytorch"},
            "images": [{"image": PT, "family": "pytorch", "release_tag": "pytorch-v1.4.0", "cuda_floor": "13.0"}],
            "skipped": [],
        }
        return S.build_report(
            plan, {"results": rows, "spend": {"cap_usd": 50, "spent_usd": 3.2}},
            run_url="https://run", log_url="https://run/job/1", commit="abc",
        )

    def test_states_and_derived_lists(self):
        rep = self._report([
            _row(PT, "FAIL", "RTX 5080", "13.0", "CUDA/GPU functional check failed",
                 cloud="COMMUNITY", gpu_id="NVIDIA GeForce RTX 5080"),
            _row(PT, "PASS", "B200", "13.0", gpu_id="NVIDIA B200"),
            _row(PT, "SKIP", "B200", "13.1", "spend cap reached: $50.00 of $50.00"),
        ])
        img = rep["images"][0]
        cells = {(c["gpu_name"], c["cuda_version"]): c for c in img["results"]}
        self.assertEqual(cells[("RTX 5080", "13.0")]["state"], "fail")
        self.assertEqual(cells[("RTX 5080", "13.0")]["reason"], "CUDA/GPU functional check failed")
        self.assertEqual(cells[("RTX 5080", "13.0")]["log_url"], "https://run/job/1")
        self.assertEqual(cells[("B200", "13.0")]["state"], "pass")
        self.assertIsNone(cells[("B200", "13.0")]["reason"])
        self.assertEqual(cells[("B200", "13.1")]["state"], "untested")
        self.assertEqual(cells[("B200", "13.1")]["untested_reason"], "spend_cap")
        self.assertEqual(img["incompatible_gpu_ids"], ["NVIDIA GeForce RTX 5080"])
        self.assertEqual(img["recommended_gpu_ids"], ["NVIDIA B200"])
        self.assertEqual(rep["totals"], {"pass": 1, "fail": 1, "untested": 1})

    def test_untested_never_marks_incompatible(self):
        rep = self._report([
            _row(PT, "SKIP", "RTX 5080", "13.0", "no capacity"),
            _row(PT, "UNVERIFIED", "B200", "13.0", "SSH endpoint was assigned but never answered"),
        ])
        img = rep["images"][0]
        self.assertEqual(img["incompatible_gpu_ids"], [])
        self.assertEqual(img["recommended_gpu_ids"], [])
        reasons = {c["gpu_name"]: c["untested_reason"] for c in img["results"]}
        self.assertEqual(reasons, {"RTX 5080": "no_capacity", "B200": "host_unresponsive"})

    def test_missing_gpu_is_listed_untested(self):
        rep = self._report([_row(PT, "PASS", "B200", "13.0")])
        cells = [c for c in rep["images"][0]["results"] if c["gpu_name"] == "RTX 5080"]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["state"], "untested")
        self.assertIsNone(cells[0]["cuda_version"])

    def test_not_covered_placeholder_dropped_when_a_version_ran(self):
        rep = self._report([
            _row(PT, "SKIP", "RTX 5080", "", "GPU not covered: not offered in the SECURE cloud"),
            _row(PT, "PASS", "RTX 5080", "13.0", cloud="COMMUNITY"),
        ])
        cells = [c for c in rep["images"][0]["results"] if c["gpu_name"] == "RTX 5080"]
        self.assertEqual([(c["cuda_version"], c["state"]) for c in cells], [("13.0", "pass")])

    def test_not_offered_loses_to_the_other_tiers_reason(self):
        rep = self._report([
            _row(PT, "SKIP", "RTX 5080", "", "GPU not covered: not offered in the SECURE cloud (covered by the COMMUNITY pass)"),
            _row(PT, "SKIP", "RTX 5080", "", "GPU not covered: offers 13.0 but none had capacity", cloud="COMMUNITY"),
        ])
        cell = [c for c in rep["images"][0]["results"] if c["gpu_name"] == "RTX 5080"][0]
        self.assertEqual(cell["untested_reason"], "no_capacity")
        self.assertEqual(cell["cloud"], "COMMUNITY")

    def test_mixed_verdicts_are_partial(self):
        rep = self._report([
            _row(PT, "PASS", "B200", "13.0", gpu_id="NVIDIA B200"),
            _row(PT, "FAIL", "B200", "13.1", "x", gpu_id="NVIDIA B200"),
        ])
        img = rep["images"][0]
        self.assertEqual(img["partial_gpu_ids"], ["NVIDIA B200"])
        self.assertNotIn("NVIDIA B200", img["incompatible_gpu_ids"])

    def test_report_command_writes_per_family_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan = {
                "config": CFG, "released": {"pytorch-v1.4.0": "pytorch"},
                "images": [{"image": PT, "family": "pytorch", "release_tag": "pytorch-v1.4.0", "cuda_floor": "13.0"}],
                "skipped": [],
            }
            (tmp / "plan.json").write_text(json.dumps(plan))
            (tmp / "results.json").write_text(json.dumps({"results": [_row(PT, "PASS", "B200", "13.0")]}))
            rc = S.main([
                "report", "--plan", str(tmp / "plan.json"), "--results", str(tmp / "results.json"),
                "--out-dir", str(tmp / "out"), "--run-url", "u",
            ])
            self.assertEqual(rc, 0)
            per_family = json.loads((tmp / "out" / "pytorch-v1.4.0.json").read_text())
            self.assertEqual(per_family["release_tag"], "pytorch-v1.4.0")
            self.assertEqual(per_family["schema_version"], 1)

    def test_report_command_refuses_without_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan = {
                "config": CFG, "released": {"pytorch-v1.4.0": "pytorch"},
                "images": [{"image": PT, "family": "pytorch", "release_tag": "pytorch-v1.4.0", "cuda_floor": "13.0"}],
                "skipped": [],
            }
            (tmp / "plan.json").write_text(json.dumps(plan))
            (tmp / "empty.json").write_text(json.dumps({"results": []}))
            for results in (tmp / "missing.json", tmp / "empty.json"):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = S.main([
                        "report", "--plan", str(tmp / "plan.json"), "--results", str(results),
                        "--out-dir", str(tmp / "out"), "--run-url", "u",
                    ])
                self.assertEqual(rc, 1, results.name)
                self.assertFalse((tmp / "out").exists(), results.name)


class CatchUp(unittest.TestCase):
    NOW = 1_800_000_000.0
    DAY = 86400.0

    def test_candidates_are_recent_family_tags_behind_the_commit(self):
        tags = [
            {"tag": "pytorch-v1.4.1", "commit": "head", "date": self.NOW},
            {"tag": "pytorch-v1.4.0", "commit": "c2", "date": self.NOW - self.DAY},
            {"tag": "base-v1.2.0", "commit": "c1", "date": self.NOW - 2 * self.DAY},
            {"tag": "base-v1.1.0", "commit": "c0", "date": self.NOW - 5 * self.DAY},
            {"tag": "unknown-v1.0.0", "commit": "c2", "date": self.NOW},
            {"tag": "v9", "commit": "c2", "date": self.NOW},
        ]
        out = S.catch_up_candidates(tags, GRAPH, sha="head", now=self.NOW, days=3)
        self.assertEqual([t["tag"] for t in out], ["base-v1.2.0", "pytorch-v1.4.0"])

    def _releases(self, *, force, has_result):
        def git(*args):
            if args[0] == "tag":
                return "pytorch-v1.4.1\nnot-a-family\n"
            fmt = "{}\t{}\t\t{:.0f}\n"
            return (
                fmt.format("pytorch-v1.4.1", "head", self.NOW)
                + fmt.format("base-v1.2.0", "c1", self.NOW - self.DAY)
                + fmt.format("comfyui-v1.0.0", "c1", self.NOW - self.DAY)
                + fmt.format("pytorch-v1.3.0", "c0", self.NOW - self.DAY)
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "releases.json"
            with mock.patch.object(S, "_git", side_effect=git), \
                    mock.patch.object(S, "_has_result", side_effect=lambda _r, t: has_result[t]), \
                    mock.patch.object(S, "_release_run_for", side_effect=lambda _r, c: {"c1": 11}.get(c)), \
                    mock.patch.object(S.time, "time", return_value=self.NOW), \
                    mock.patch.dict(S.os.environ, {"GH_REPO": "o/r"}), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = S.main([
                    "releases", "--graph", str(self._graph(Path(tmp))), "--sha", "head",
                    "--run-id", "99", "--out", str(out), *(["--force"] if force else []),
                ])
            self.assertEqual(rc, 0)
            return json.loads(out.read_text())

    def _graph(self, tmp):
        path = tmp / "families.yml"
        path.write_text(json.dumps({"families": GRAPH}))
        return path

    def test_unswept_releases_behind_are_caught_up(self):
        rels = self._releases(force=False, has_result={
            "pytorch-v1.4.1": False, "base-v1.2.0": False,
            "comfyui-v1.0.0": True, "pytorch-v1.3.0": False,
        })
        self.assertEqual(rels[0], {"run_id": 99, "sha": "head", "tags": ["pytorch-v1.4.1"], "catch_up": False})
        # comfyui at c1 already has a result; base at c1 doesn't.
        self.assertEqual(rels[1]["tags"], ["base-v1.2.0"])
        self.assertEqual(rels[1]["run_id"], 11)
        # No release run found for c0: kept, with a note, so the report says so.
        self.assertIsNone(rels[2]["run_id"])
        self.assertIn("not swept", rels[2]["note"])

    def test_own_tags_already_caught_up_are_not_swept_twice(self):
        has = {"pytorch-v1.4.1": True, "base-v1.2.0": True, "comfyui-v1.0.0": True, "pytorch-v1.3.0": True}
        self.assertEqual(self._releases(force=False, has_result=has), [])
        # A dispatch is an explicit re-sweep.
        self.assertEqual(self._releases(force=True, has_result=has)[0]["tags"], ["pytorch-v1.4.1"])

    def test_plan_merges_releases_and_reports_expired_refs(self):
        pt_old = PT.replace("1.4.0", "1.3.0")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for run, refs in (("1", [PT, BASE_GPU]), ("2", [pt_old])):
                (root / run / "pytorch-refs").mkdir(parents=True)
                (root / run / "pytorch-refs" / "refs.json").write_text(json.dumps(refs))
            releases = [
                {"run_id": 1, "sha": "head", "tags": ["pytorch-v1.4.0"], "catch_up": False},
                {"run_id": 2, "sha": "c2", "tags": ["pytorch-v1.3.0"], "catch_up": True},
                {"run_id": 3, "sha": "c3", "tags": ["base-v1.1.0"], "catch_up": True},
            ]
            tags, out = S.plan_releases(CFG, GRAPH, releases, root)
        self.assertEqual(tags, {"pytorch-v1.4.0": "pytorch", "pytorch-v1.3.0": "pytorch"})
        by_image = {i["image"]: i for i in out["images"]}
        self.assertEqual(by_image[PT]["release_tag"], "pytorch-v1.4.0")
        self.assertEqual(by_image[pt_old]["commit"], "c2")
        skipped = {s["image"]: s["reason"] for s in out["skipped"]}
        self.assertIn("not released", skipped[BASE_GPU])
        self.assertIn("no refs from release run 3", skipped["base-v1.1.0"])

    def test_report_writes_one_file_per_tag_of_the_same_family(self):
        pt_old = PT.replace("1.4.0", "1.3.0")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan = {
                "config": CFG,
                "released": {"pytorch-v1.4.0": "pytorch", "pytorch-v1.3.0": "pytorch"},
                "images": [
                    {"image": PT, "family": "pytorch", "release_tag": "pytorch-v1.4.0", "cuda_floor": "13.0", "commit": "head"},
                    {"image": pt_old, "family": "pytorch", "release_tag": "pytorch-v1.3.0", "cuda_floor": "13.0", "commit": "c2"},
                ],
                "skipped": [],
            }
            (tmp / "plan.json").write_text(json.dumps(plan))
            (tmp / "results.json").write_text(json.dumps({"results": [
                _row(PT, "PASS", "B200", "13.0"), _row(pt_old, "FAIL", "B200", "13.0"),
            ]}))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = S.main([
                    "report", "--plan", str(tmp / "plan.json"), "--results", str(tmp / "results.json"),
                    "--out-dir", str(tmp / "out"), "--run-url", "u", "--commit", "head",
                ])
            self.assertEqual(rc, 0)
            old = json.loads((tmp / "out" / "pytorch-v1.3.0.json").read_text())
            self.assertEqual([i["image"] for i in old["images"]], [pt_old])
            self.assertEqual(old["commit"], "c2")
            self.assertEqual(old["totals"]["fail"], 1)


class Reap(unittest.TestCase):
    def test_sweep_pod_matching(self):
        self.assertTrue(S.is_sweep_pod("smoketest-1700000000-0042-1-sweep123", "sweep123"))
        self.assertFalse(S.is_sweep_pod("smoketest-1700000000-0042-1-sweep123", "sweep12"))
        self.assertTrue(S.is_sweep_pod("smoketest-1700000000-0042-1-sweep123"))
        # A PR smoke-test pod or a human's pod is never an "any sweep" pod.
        self.assertFalse(S.is_sweep_pod("smoketest-1700000000-0042-1"))
        self.assertFalse(S.is_sweep_pod("my-pod-sweep123"))


if __name__ == "__main__":
    unittest.main()
