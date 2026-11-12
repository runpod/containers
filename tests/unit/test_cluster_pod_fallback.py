"""CLUSTER_POD_FALLBACK: a cluster group with no Instant Cluster capacity is
re-tested on a single pod, and the pod result replaces its SKIP row."""

import unittest
from unittest import mock

import test_images as T
from runpod_smoke import config

IMAGE = "runpod/pytorch-cluster:2.3.0-cu1281-torch2121-ubuntu2404"
MANIFEST = {
    "pytorch_cluster": {
        "images": [IMAGE],
        "cluster": True,
        "instances": ["NVIDIA H100 80GB HBM3"],
        "exclude_instances": ["*GB10*"],
    },
    "pytorch": {"images": ["runpod/pytorch:x"], "max_price_per_hour": 1.0},
}


def skip(image=IMAGE):
    return (image, "SKIP", "no capacity", "", "", "", "SECURE")


class ClusterPodFallback(unittest.TestCase):
    def setUp(self):
        patches = {
            "CLUSTER_POD_FALLBACK": True,
            "CLUSTER_POD_FALLBACK_MAX_PRICE": 0.8,
            "CLUSTER_POD_FALLBACK_MIN_VRAM_GB": 24,
            "CLOUD_TYPES": ["SECURE"],
            "CLOUD_TYPE": "SECURE",
            "GROUP_CLUSTER": {"pytorch_cluster": True},
        }
        for name, value in patches.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, results, *, pods=("RTX A5000",), outcome="PASS", note=""):
        seen = {}

        def resolve(group, contents):
            seen["group"], seen["contents"] = group, contents
            seen["cluster_at_resolve"] = config.GROUP_CLUSTER[group]
            return list(pods)

        def run_jobs(jobs, out):
            seen["jobs"] = jobs
            out.extend(
                (job[0], outcome, note, job[2][0], "12.8", "", job[4]) for job in jobs
            )

        with mock.patch.object(T, "resolve_instances", resolve), \
             mock.patch.object(T, "_run_jobs", run_jobs):
            T._run_cluster_pod_fallback(MANIFEST, None, results)
        return seen

    def test_skip_is_retested_on_a_pod_and_replaced(self):
        results = [skip(), ("runpod/pytorch:x", "PASS", "", "L4", "", "", "SECURE")]
        seen = self._run(results)
        self.assertEqual(
            seen["jobs"], [(IMAGE, "pytorch_cluster", ["RTX A5000"], "", "SECURE")]
        )
        self.assertEqual(results[0][:4], (IMAGE, "PASS", T.FALLBACK_NOTE, "RTX A5000"))
        self.assertEqual(results[1][1], "PASS")  # other groups untouched
        # The pod run must take the pod path, not the cluster runner.
        self.assertFalse(seen["cluster_at_resolve"])
        self.assertFalse(config.GROUP_CLUSTER["pytorch_cluster"])

    def test_pod_candidates_use_the_fallback_budget_not_cluster_gpus(self):
        seen = self._run([skip()])
        contents = seen["contents"]
        self.assertNotIn("instances", contents)
        self.assertEqual(contents["max_price_per_hour"], 0.8)
        self.assertEqual(contents["min_vram_gb"], 24)
        self.assertEqual(contents["manufacturer"], "Nvidia")
        self.assertEqual(contents["exclude_instances"], ["*GB10*"])

    def test_pod_failure_keeps_its_detail(self):
        results = [skip()]
        self._run(results, outcome="FAIL", note="cuda check failed")
        self.assertEqual(results[0][1], "FAIL")
        self.assertEqual(results[0][2], f"{T.FALLBACK_NOTE}; cuda check failed")

    def test_off_by_default(self):
        with mock.patch.object(config, "CLUSTER_POD_FALLBACK", False):
            results = [skip()]
            seen = self._run(results)
        self.assertNotIn("jobs", seen)
        self.assertEqual(results[0][1], "SKIP")

    def test_cluster_that_ran_is_not_retested(self):
        for status in ("PASS", "FAIL", "UNVERIFIED"):
            with self.subTest(status=status):
                results = [(IMAGE, status, "", "H100", "", "", "SECURE")]
                seen = self._run(results)
                self.assertNotIn("jobs", seen)
                self.assertEqual(results[0][1], status)

    def test_no_pod_candidates_keeps_the_skip(self):
        results = [skip()]
        seen = self._run(results, pods=())
        self.assertNotIn("jobs", seen)
        self.assertEqual(results[0][1], "SKIP")
        self.assertTrue(config.GROUP_CLUSTER["pytorch_cluster"])


if __name__ == "__main__":
    unittest.main()
