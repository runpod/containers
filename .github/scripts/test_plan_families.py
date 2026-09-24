#!/usr/bin/env python3
"""Unit tests for plan_families.py:

    python3 .github/scripts/test_plan_families.py

The coverage test is the important one: a template added without a line in
families.yml would silently never be built or released again.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plan_families as P  # noqa: E402


GRAPH = {
    "base": {"paths": ["t/base/**"], "depends_on": []},
    "pytorch": {"paths": ["t/pytorch/**"], "depends_on": ["base"]},
    "cluster": {"paths": ["t/cluster/**"], "depends_on": ["pytorch"]},
    "rocm": {"paths": ["t/rocm/**", "t/base/**"], "depends_on": []},
    "comfyui": {"paths": ["t/comfyui/**"], "depends_on": []},
}


class Selection(unittest.TestCase):
    def test_one_template_selects_only_itself(self):
        self.assertEqual(P.plan(GRAPH, ["t/comfyui/Dockerfile"], False), ["comfyui"])

    def test_nothing_relevant_changed(self):
        self.assertEqual(P.plan(GRAPH, ["README.md"], False), [])

    def test_dependents_come_along(self):
        self.assertEqual(
            P.plan(GRAPH, ["t/pytorch/Dockerfile"], False), ["pytorch", "cluster"]
        )

    def test_dependents_are_transitive(self):
        got = P.plan(GRAPH, ["t/base/Dockerfile"], False)
        self.assertEqual(sorted(got), ["base", "cluster", "pytorch", "rocm"])
        self.assertLess(got.index("base"), got.index("pytorch"))
        self.assertLess(got.index("pytorch"), got.index("cluster"))

    def test_shared_sources_select_without_a_dependency(self):
        """rocm builds base's Dockerfile but not FROM base's image."""
        self.assertIn("rocm", P.plan(GRAPH, ["t/base/Dockerfile"], False))
        self.assertEqual(P.plan(GRAPH, ["t/rocm/req.txt"], False), ["rocm"])

    def test_all_selects_everything(self):
        self.assertEqual(sorted(P.plan(GRAPH, [], True)), sorted(GRAPH))

    def test_a_sibling_directory_is_not_a_prefix_match(self):
        self.assertEqual(P.plan(GRAPH, ["t/base-old/Dockerfile"], False), [])


class PlanSinceRelease(unittest.TestCase):
    """A push diff misses whatever arrived while an earlier release ran."""

    def test_each_family_is_judged_against_its_own_release(self):
        changed = {
            "base": [],
            "pytorch": ["t/pytorch/Dockerfile"],
            "cluster": [],
            "rocm": [],
            "comfyui": ["t/comfyui/Dockerfile"],
        }
        got = P.plan_since_release(GRAPH, lambda name: changed[name])
        self.assertEqual(sorted(got), ["cluster", "comfyui", "pytorch"])
        self.assertLess(got.index("pytorch"), got.index("cluster"))

    def test_a_family_left_behind_by_a_dropped_run_is_picked_up(self):
        """comfyui changed two pushes ago and never got released."""
        changed = {name: [] for name in GRAPH}
        changed["comfyui"] = ["t/comfyui/scripts/start.sh"]
        self.assertEqual(P.plan_since_release(GRAPH, lambda n: changed[n]), ["comfyui"])

    def test_nothing_outstanding_plans_nothing(self):
        self.assertEqual(P.plan_since_release(GRAPH, lambda n: []), [])


class BuildOrder(unittest.TestCase):
    def test_a_family_never_precedes_what_it_builds_from(self):
        order = P.plan(GRAPH, [], True)
        self.assertLess(order.index("base"), order.index("pytorch"))
        self.assertLess(order.index("pytorch"), order.index("cluster"))

    def test_unselected_dependencies_do_not_block(self):
        """pytorch is already published, so cluster alone can go first."""
        self.assertEqual(P.plan(GRAPH, ["t/cluster/Dockerfile"], False), ["cluster"])

    def test_cycles_are_reported(self):
        cyclic = {
            "a": {"paths": ["t/a/**"], "depends_on": ["b"]},
            "b": {"paths": ["t/b/**"], "depends_on": ["a"]},
        }
        with self.assertRaises(P.GraphError):
            P.plan(cyclic, [], True)


class Pathspecs(unittest.TestCase):
    """`git log -- <spec>` is how the release notes find a family's commits."""

    def test_a_directory_glob_becomes_a_directory(self):
        self.assertEqual(
            P.git_pathspecs(["official-templates/base/**"]),
            ["official-templates/base/"],
        )

    def test_a_plain_path_is_left_alone(self):
        self.assertEqual(P.git_pathspecs(["bake.sh"]), ["bake.sh"])


class GraphFile(unittest.TestCase):
    def _write(self, text: str) -> Path:
        path = Path(tempfile.mkdtemp()) / "families.yml"
        path.write_text(text)
        return path

    def test_unknown_dependency_is_fatal(self):
        path = self._write(
            "families:\n  a:\n    paths: [x/**]\n    depends_on: [ghost]\n"
        )
        with self.assertRaises(P.GraphError):
            P.load_graph(path)

    def test_a_family_without_paths_is_fatal(self):
        path = self._write("families:\n  a:\n    depends_on: []\n")
        with self.assertRaises(P.GraphError):
            P.load_graph(path)

    def test_real_graph_loads_and_orders(self):
        graph = P.load_graph(P.DEFAULT_GRAPH)
        order = P.build_order(graph, set(graph))
        for name, spec in graph.items():
            for dep in spec["depends_on"]:
                self.assertLess(order.index(dep), order.index(name), name)

    def test_each_family_has_a_build_job_named_after_it(self):
        """manual-release looks up '<workflow> / build-<family>' by name."""
        import yaml

        graph = P.load_graph(P.DEFAULT_GRAPH)
        for name, spec in graph.items():
            path = P.REPO_ROOT / f".github/workflows/{spec['workflow']}.yml"
            jobs = yaml.safe_load(path.read_text())["jobs"]
            self.assertIn(f"build-{name}", jobs)

    def test_every_family_is_covered_by_a_build_workflow(self):
        """release.yml calls a workflow only if the plan names it."""
        graph = P.load_graph(P.DEFAULT_GRAPH)
        known = {"base", "nvidia", "rocm", "comfyui", "sandbox"}
        for name, spec in graph.items():
            self.assertIn(spec["workflow"], known, f"{name} has no build workflow")

    def test_every_family_publishes_somewhere(self):
        """manual-release checks the family's repo, so it must be known."""
        graph = P.load_graph(P.DEFAULT_GRAPH)
        for name, spec in graph.items():
            self.assertTrue(
                spec["image_repo"].startswith("runpod/"),
                f"{name} has no image_repo",
            )

    def test_every_template_is_in_the_graph(self):
        graph = P.load_graph(P.DEFAULT_GRAPH)
        templates = {
            d.name
            for d in (P.REPO_ROOT / "official-templates").iterdir()
            if d.is_dir() and d.name != "shared"
        }
        self.assertEqual(templates, set(graph))

    def test_a_base_dockerfile_change_rebuilds_rocm_and_nvidia(self):
        graph = P.load_graph(P.DEFAULT_GRAPH)
        got = P.plan(graph, ["official-templates/base/Dockerfile"], False)
        self.assertEqual(
            sorted(got),
            [
                "autoresearch",
                "base",
                "nvidia-pytorch",
                "pytorch",
                "pytorch-cluster",
                "rocm",
            ],
        )

    def test_a_comfyui_change_touches_nothing_else(self):
        graph = P.load_graph(P.DEFAULT_GRAPH)
        self.assertEqual(
            P.plan(graph, ["official-templates/comfyui/scripts/start.sh"], False),
            ["comfyui"],
        )


if __name__ == "__main__":
    unittest.main()
