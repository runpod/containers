#!/usr/bin/env python3
"""Unit tests for gpu_sweep.py — plan and report, no network.

    python3 .github/scripts/test_gpu_sweep.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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
            "released": {"pytorch": "pytorch-v1.4.0"},
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
                "config": CFG, "released": {"pytorch": "pytorch-v1.4.0"},
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


if __name__ == "__main__":
    unittest.main()
