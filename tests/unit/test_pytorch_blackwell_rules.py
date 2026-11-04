"""The scoped Blackwell blocks in base.yml must cover the real build matrix.

cu126 wheels predate Blackwell, and the cu129 index's torchvision is built
without it, so every image whose torch comes from either index fails on
B200 / B300 / RTX 50-series. base.yml blocks those per ref glob
(`exclude-instances-for`), which is easy to get wrong when a combo is added
or its whl_src changes. This runs the generator on what `docker buildx bake
--print` actually builds, using the rules as written in base.yml.

The other direction is checked too: an image on a Blackwell-capable index
must keep Blackwell, or the scoping has quietly fallen back to a blanket
block and the coverage this was for is gone.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE_YML = REPO / ".github" / "workflows" / "base.yml"
GENERATOR = REPO / ".github" / "scripts" / "generate_test_manifest.py"
CUDA_GROUPS = ["cu1281", "cu1290", "cu1300", "cu1320"]

# Catalog display names, one per Blackwell family the patterns have to catch.
BLACKWELL = ["B200", "B300", "B300 MIG 34GB", "RTX 5090", "RTX PRO 6000"]
NO_BLACKWELL_INDEXES = {"126", "129"}

_COMBO = re.compile(r"-cu(\d+)-torch(\d+)-")


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_test_manifest", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bake_targets(template: str) -> dict:
    out = subprocess.run(
        ["docker", "buildx", "bake",
         "-f", "official-templates/shared/versions.hcl",
         "-f", f"official-templates/{template}/docker-bake.hcl",
         "--print", *CUDA_GROUPS],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)["target"]


def _block(job: str, key: str) -> list[str]:
    """Lines of the `key: |` block scalar under `job` in base.yml."""
    lines = BASE_YML.read_text().splitlines()
    start = lines.index(f"  {job}:")
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"  [a-z][a-z0-9-]*:$", lines[i])), len(lines))
    out: list[str] = []
    indent = None
    for line in lines[start:end]:
        if indent is None:
            if line.strip() == f"{key}: |":
                indent = len(line) - len(line.lstrip()) + 2
            continue
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        if line.strip() and not line.strip().startswith("#"):
            out.append(line.strip())
    return out


def _skip_without_bake() -> None:
    if shutil.which("docker") is None:
        # CI must run this: the whole point is to catch matrix drift there.
        if os.environ.get("CI"):
            raise AssertionError("docker buildx is required in CI")
        raise unittest.SkipTest("docker not installed")


class BlackwellRulesCoverMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _skip_without_bake()
        cls.gen = _load_generator()
        pytorch = _bake_targets("pytorch")
        cls.pytorch_refs = {t["tags"][0]: t["args"]["WHEEL_SRC"]
                            for t in pytorch.values()}
        # The cluster layer installs no torch of its own, so its index is
        # the one of the pytorch image it builds FROM.
        by_combo = {_COMBO.search(ref).groups(): src
                    for ref, src in cls.pytorch_refs.items()}
        cls.cluster_refs = {
            t["tags"][0]: by_combo[_COMBO.search(t["args"]["BASE_IMAGE"]).groups()]
            for t in _bake_targets("pytorch-cluster").values()
        }

    def _assert_job(self, job: str, refs: dict[str, str]) -> None:
        self.assertTrue(refs, f"{job}: bake printed no targets")
        rules = [self.gen._scoped_exclude_spec(r)
                 for r in _block(job, "exclude-instances-for")]
        self.assertTrue(rules, f"{job}: no exclude-instances-for in base.yml")
        groups = self.gen.build_groups(
            "gpu", sorted(refs), budget=1.0, min_vram_gb=16,
            manufacturer="Nvidia",
            exclude_instances=_block(job, "exclude-instances"),
            scoped_excludes=rules,
        )
        for body in groups.values():
            patterns = [p.lower() for p in body.get("exclude_instances", [])]
            for ref in body["images"]:
                blocked = [gpu for gpu in BLACKWELL
                           if any(fnmatch.fnmatchcase(gpu.lower(), p)
                                  for p in patterns)]
                with self.subTest(job=job, ref=ref, whl_src=refs[ref]):
                    if refs[ref] in NO_BLACKWELL_INDEXES:
                        self.assertEqual(blocked, BLACKWELL,
                                         "cu126/cu129 image can land on Blackwell")
                    else:
                        self.assertEqual(blocked, [],
                                         "Blackwell-capable image lost Blackwell")

    def test_pytorch(self) -> None:
        self._assert_job("test-pytorch", self.pytorch_refs)

    def test_pytorch_cluster(self) -> None:
        self._assert_job("test-pytorch-cluster", self.cluster_refs)


if __name__ == "__main__":
    unittest.main()
