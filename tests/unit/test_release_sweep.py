"""Harness pieces the release GPU sweep relies on.

- `cuda_versions: allowed` tests only host CUDA versions the image can be
  scheduled on (at or above its floor).
- The spend cap is enforced before a pod exists: a job that doesn't fit is
  SKIP (untested), never FAIL, and no pod is created for it.
- Cloud tiers are deduplicated, and a cap trims CUDA depth before it drops
  an image x GPU pair.
- Sweep pods carry a run suffix so the run can reap its own leftovers.
"""

import unittest
from unittest import mock

import test_images as T
from runpod_smoke import config, runner, spend
from runpod_smoke.instances import below_floor_reason, cuda_axis_for


def _gpu(name, gpu_id, *, secure=1.0, community=0.0, cuda=("12.8", "12.9", "13.0")):
    return {
        "id": gpu_id, "displayName": name, "memoryInGb": 24,
        "manufacturer": "Nvidia", "securePrice": secure,
        "communityPrice": community, "availability": "HIGH",
        "cudaVersions": list(cuda), "cudaVersionsAvailable": list(cuda),
        "secure": secure > 0, "community": community > 0,
    }


CATALOG = [
    _gpu("RTX 5080", "NVIDIA GeForce RTX 5080", secure=0, community=0.5),
    _gpu("B200", "NVIDIA B200", secure=6.0),
    _gpu("L4", "NVIDIA L4", secure=0.5, community=0.4, cuda=("12.4", "12.8")),
]

CU129 = "runpod/pytorch:1.4.0-cu1290-torch280-ubuntu2404"
NGC = "runpod/nvidia-pytorch:1.0.0-25.11"


class _ConfigReset(unittest.TestCase):
    def setUp(self):
        for d in (
            config.GROUP_CUDA_ALL, config.GROUP_CUDA_VERSIONS,
            config.GROUP_CUDA_ALLOWED, config.GROUP_CUDA_FLOOR,
            config.GROUP_MIN_CUDA, config.GROUP_CHECK_ALL_GPU,
        ):
            d.clear()
        config.GPU_CATALOG[:] = CATALOG
        self.addCleanup(config.GPU_CATALOG.clear)
        spend.reset()
        self.addCleanup(spend.reset)
        patcher = mock.patch.object(T, "log")
        patcher.start()
        self.addCleanup(patcher.stop)


class AllowedCudaAxis(_ConfigReset):
    def test_tag_floor_drops_older_hosts(self):
        T._apply_cuda_axis("g", "allowed")
        self.assertEqual(cuda_axis_for("g", "RTX 5080", CU129), ["13.0", "12.9"])

    def test_group_floor_used_when_tag_has_none(self):
        config.GROUP_MIN_CUDA["g"] = "13.0"
        T._apply_cuda_axis("g", "allowed")
        # The axis drops min_cuda_version (the API rejects both fields)...
        self.assertNotIn("g", config.GROUP_MIN_CUDA)
        # ...but the floor survives for the axis itself.
        self.assertEqual(cuda_axis_for("g", "B200", NGC), ["13.0"])

    def test_all_keeps_every_version(self):
        T._apply_cuda_axis("g", "all")
        self.assertEqual(cuda_axis_for("g", "B200", CU129), ["13.0", "12.9", "12.8"])

    def test_gpu_entirely_below_floor_says_so(self):
        T._apply_cuda_axis("g", "allowed")
        results: list = []
        jobs = T._cuda_matrix_jobs(CU129, "g", ["L4"], results, "SECURE")
        self.assertEqual(jobs, [])
        self.assertEqual(results[0][1], "SKIP")
        self.assertIn("below the image's CUDA floor 12.9", results[0][2])
        self.assertTrue(below_floor_reason("g", "L4", CU129))


class SpendCap(_ConfigReset):
    def setUp(self):
        super().setUp()
        for name, value in (("SPEND_CAP_USD", 5.0), ("SPEND_RESERVE_MINUTES", 30.0)):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        spend.record_prices("SECURE", CATALOG)
        spend.record_prices("COMMUNITY", CATALOG)

    def test_hold_then_settle(self):
        token, why = spend.reserve("B200", "SECURE")  # $3 hold
        self.assertTrue(token, why)
        # $3 held + $3 more would pass the $5 cap.
        denied, why = spend.reserve("B200", "SECURE")
        self.assertIsNone(denied)
        self.assertIn("spend cap reached", why)
        spend.settle(token, 600)  # 10 min of $6/hr = $1
        self.assertAlmostEqual(spend.spent(), 1.0)
        self.assertTrue(spend.reserve("B200", "SECURE")[0])

    def test_unknown_gpu_charged_at_highest_price(self):
        self.assertEqual(spend.price_for("Mystery GPU", "SECURE"), 6.0)

    def test_no_prices_refuses(self):
        spend.reset()
        token, why = spend.reserve("B200", "SECURE")
        self.assertIsNone(token)
        self.assertIn("no GPU prices", why)

    def test_over_cap_creates_no_pod_and_is_untested(self):
        spend.reserve("B200", "SECURE")  # leaves $2 of room
        with mock.patch.object(runner, "_create_pod_with_retries") as create, \
                mock.patch.object(runner, "log"), \
                mock.patch.object(runner, "set_worker_context"), \
                mock.patch.object(runner, "resolve_gpu_id", return_value="NVIDIA B200"):
            status, note, inst, _cuda = runner.test_image(CU129, ["B200"], "g", "13.0", "SECURE")
        create.assert_not_called()
        self.assertEqual(status, "SKIP")
        self.assertIn("spend cap", note)
        self.assertEqual(inst, "B200")

    def test_failed_create_releases_hold(self):
        with mock.patch.object(
            runner, "_create_pod_with_retries", return_value=(None, "UNAVAILABLE", ""),
        ), mock.patch.object(runner, "log"), \
                mock.patch.object(runner, "resolve_gpu_id", return_value="NVIDIA B200"):
            runner.test_pair(CU129, "B200", "g", "13.0", "SECURE")
        # A leaked $3 hold would leave no room for another $3 under the $5
        # cap; released, the next one fits and nothing was spent.
        self.assertTrue(spend.reserve("B200", "SECURE")[0])
        self.assertEqual(spend.spent(), 0.0)

    def test_disabled_cap_is_a_noop(self):
        with mock.patch.object(config, "SPEND_CAP_USD", 0.0):
            self.assertEqual(spend.reserve("B200", "SECURE"), (0, ""))


class PlanShaping(_ConfigReset):
    def test_dedupe_keeps_first_tier_and_drops_covered_gaps(self):
        jobs = [
            (CU129, "g", ["B200"], "13.0", "SECURE"),
            (CU129, "g", ["L4"], "12.8", "SECURE"),
            (CU129, "g", ["L4"], "12.8", "COMMUNITY"),
            (CU129, "g", ["RTX 5080"], "13.0", "COMMUNITY"),
        ]
        results = [
            (CU129, "SKIP", "GPU not covered: not offered in the SECURE cloud",
             "RTX 5080", "", "", "SECURE"),
            (CU129, "SKIP", "GPU not covered: not in the GPU catalog",
             "H100 SXM", "", "", "SECURE"),
        ]
        kept = T._dedupe_cloud_tiers(jobs, results)
        self.assertEqual(
            [(j[2][0], j[4]) for j in kept],
            [("B200", "SECURE"), ("L4", "SECURE"), ("RTX 5080", "COMMUNITY")],
        )
        self.assertEqual([r[3] for r in results], ["H100 SXM"])

    def test_spread_puts_newest_cuda_of_every_pair_first(self):
        jobs = [
            ("a", "g", ["B200"], "13.0", "SECURE"),
            ("a", "g", ["B200"], "12.9", "SECURE"),
            ("a", "g", ["L4"], "12.8", "SECURE"),
            ("b", "g", ["B200"], "13.0", "SECURE"),
            ("b", "g", ["B200"], "12.9", "SECURE"),
        ]
        order = [(j[0], j[2][0], j[3]) for j in T._spread_cuda_versions(jobs)]
        self.assertEqual(order, [
            # depth 0: first-listed GPU for every image, then the next GPU
            ("a", "B200", "13.0"), ("b", "B200", "13.0"), ("a", "L4", "12.8"),
            # depth 1
            ("a", "B200", "12.9"), ("b", "B200", "12.9"),
        ])

    def test_last_family_is_not_starved(self):
        # Manifest order puts every 'early' job before any 'late' one; under
        # a cap that only fits the first few, 'late' must still get its
        # top-priority GPU.
        jobs = [
            (img, "g", [gpu], "13.0", "SECURE")
            for img in ("early1", "early2", "late")
            for gpu in ("RTX 5080", "B200", "L4")
        ]
        first_three = [(j[0], j[2][0]) for j in T._spread_cuda_versions(jobs)[:3]]
        self.assertEqual(first_three, [
            ("early1", "RTX 5080"), ("early2", "RTX 5080"), ("late", "RTX 5080"),
        ])

    def test_gpu_id_for_results(self):
        with mock.patch.dict(config.GPU_ID_MAP, {"RTX 5080": "NVIDIA GeForce RTX 5080"}):
            self.assertEqual(T._gpu_id_for("rtx 5080"), "NVIDIA GeForce RTX 5080")
            self.assertEqual(T._gpu_id_for("RTX 5080, L4"), "")
            self.assertEqual(T._gpu_id_for(""), "")


class PodNameSuffix(unittest.TestCase):
    def test_suffix_is_appended_after_the_epoch_fields(self):
        captured = {}

        def fake_create(_image, _gpu, name, **_kw):
            captured["name"] = name
            return "pod1", "", ""

        with mock.patch.object(config, "POD_NAME_SUFFIX", "sweep123"), \
                mock.patch.object(runner, "create_pod", side_effect=fake_create):
            runner._create_pod_with_retries(CU129, "B200", "NVIDIA B200", False, "g")
        parts = captured["name"].split("-")
        self.assertEqual(parts[0], "smoketest")
        self.assertTrue(parts[1].isdigit())  # reap-pods.yml reads the epoch here
        self.assertEqual(parts[-1], "sweep123")


if __name__ == "__main__":
    unittest.main()
