"""CLUSTER_POD_FALLBACK: a cluster group with no Instant Cluster capacity is
re-tested on a single pod, and the pod result replaces its SKIP row."""

import re
import unittest
from unittest import mock

import test_images as T
from runpod_smoke import cluster_report, config

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


CLUSTER_GPUS = "NVIDIA A100-SXM4-80GB, NVIDIA H100 80GB HBM3"
POD_RUN = {
    "instance": "RTX A5000",
    "pod_id": "pod123",
    "host_cuda": "13.2",
    "steps": [
        ("SSH ready", "ok"), ("CUDA / torch", "ok"), ("Jupyter via proxy", "ok"),
        ("log scan", "ok"), ("alive after 60s", "ok"),
    ],
}


def skip(image=IMAGE):
    return (image, "SKIP", "no capacity", CLUSTER_GPUS, "", "", "SECURE")


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
        reports = mock.patch.object(cluster_report, "FALLBACK_REPORTS", [])
        reports.start()
        self.addCleanup(reports.stop)

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
             mock.patch.object(T, "_run_jobs", run_jobs), \
             mock.patch.object(T, "pod_run", lambda image, group: POD_RUN):
            T._run_cluster_pod_fallback(MANIFEST, None, results, waited_s=1500)
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


    def test_summary_says_why_where_and_what_ran(self):
        with mock.patch.object(config, "SKIP_RETRIES", 5), \
             mock.patch.object(config, "ON_SKIP", "warn"), \
             mock.patch.object(
                 config, "GROUP_CLUSTER_TYPES",
                 {"pytorch_cluster": ("SLURM", "TRAINING")},
             ):
            self._run([skip()])
        (report,) = cluster_report.FALLBACK_REPORTS
        text = "\n".join(report.render_text())
        for expected in (
            f"PASS  {IMAGE}  (single pod, NOT a cluster)",
            "no 2-node Instant Cluster in 6 round(s) over 25 min",
            f"tried: {CLUSTER_GPUS}",
            "as: SLURM, TRAINING",
            "ran on: 1x RTX A5000, host CUDA 13.2 (pod pod123)",
        ):
            self.assertIn(expected, text)
        self.assertRegex(text, r"\n  CUDA / torch\s+ok\n")
        self.assertRegex(text, r"\n  alive after 60s\s+ok\n")
        for cluster_only in (
            "Grafana via proxy :8889", "Prometheus scrapes all nodes",
            "Slurm: nodes idle, srun on all",
        ):
            self.assertRegex(
                text, rf"\n  {re.escape(cluster_only)}\s+not run: needs a cluster"
            )

    def test_failed_pod_check_is_shown_and_stops_the_report(self):
        failed = dict(POD_RUN, steps=[("SSH ready", "ok"), ("CUDA / torch", "FAIL")])
        with mock.patch.object(T, "pod_run", lambda *_: failed):
            results = [skip()]
            with mock.patch.object(
                T, "_run_jobs",
                lambda jobs, out: out.extend(
                    (j[0], "FAIL", "CUDA/GPU functional check failed",
                     "RTX A5000", "", "", j[4]) for j in jobs
                ),
            ), mock.patch.object(T, "resolve_instances", lambda g, c: ["RTX A5000"]):
                T._run_cluster_pod_fallback(MANIFEST, None, results)
        text = "\n".join(cluster_report.FALLBACK_REPORTS[0].render_text())
        self.assertIn("FAIL  " + IMAGE, text)
        self.assertRegex(text, r"CUDA / torch\s+FAIL")
        self.assertIn("stopped at: CUDA/GPU functional check failed", text)


class RetryBackoff(unittest.TestCase):
    def _delays(self, backoff):
        sleeps = []
        job = (IMAGE, "pytorch_cluster", ["H100"], "", "SECURE")
        skip_result = (IMAGE, "SKIP", "no capacity", "H100", "", "", "SECURE")
        with mock.patch.object(config, "SKIP_RETRIES", 5), \
             mock.patch.object(config, "SKIP_RETRY_DELAY", 300), \
             mock.patch.object(config, "SKIP_RETRY_BACKOFF", backoff), \
             mock.patch.object(config, "ON_SKIP", "warn"), \
             mock.patch.object(T, "_run_jobs_once", lambda jobs, label="": [
                 skip_result for _ in jobs
             ]), \
             mock.patch.object(T.time, "sleep", sleeps.append):
            T._run_jobs([job], [])
        return sleeps

    def test_fixed_waits_the_same_delay_every_round(self):
        self.assertEqual(self._delays("fixed"), [300] * 5)

    def test_linear_is_still_the_default_shape(self):
        self.assertEqual(self._delays("linear"), [300, 600, 900, 1200, 1500])


if __name__ == "__main__":
    unittest.main()
