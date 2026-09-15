"""A run that tested nothing must never report success.

With explicit `instances:` plus a CUDA axis, planning can legitimately
produce no jobs — none of the named GPUs offers a version with free
capacity. That used to also produce no result rows, and `_print_summary`
read "0 FAIL, 0 SKIP" as a pass and exited 0 whatever `ON_SKIP` said.
"""

import unittest
from unittest import mock

import test_images as T
from runpod_smoke import config


CATALOG = [
    {
        "id": "NVIDIA RTX A4000", "displayName": "RTX A4000",
        "memoryInGb": 16, "manufacturer": "Nvidia",
        "securePrice": 0.25, "communityPrice": 0.2, "availability": "HIGH",
        # Offered in this tier, but nothing has free capacity right now.
        "cudaVersions": ["12.8"], "cudaVersionsAvailable": [],
        "secure": True, "community": True,
    },
    {
        "id": "NVIDIA L4", "displayName": "L4",
        "memoryInGb": 24, "manufacturer": "Nvidia",
        "securePrice": 0.49, "communityPrice": 0, "availability": "HIGH",
        "cudaVersions": ["12.8"], "cudaVersionsAvailable": [],
        "secure": True, "community": False,
    },
]

IMAGE = "runpod/pytorch:1.2.0-cu1281-torch2121-ubuntu2204"


class PlanningRecordsTheGap(unittest.TestCase):
    def setUp(self) -> None:
        for d in (
            config.GROUP_CHECK_ALL_GPU, config.GROUP_CUDA_ALL,
            config.GROUP_CUDA_VERSIONS,
        ):
            d.clear()
        config.GPU_CATALOG[:] = CATALOG
        self.addCleanup(config.GPU_CATALOG.clear)
        config.GROUP_CUDA_ALL["base_gpu"] = True
        self.manifest = {
            "base_gpu": {
                "images": [IMAGE],
                "instances": ["RTX A4000", "L4"],
                "cuda_versions": "all",
            }
        }
        self.resolved = {"base_gpu": ["RTX A4000", "L4"]}

    def _plan(self):
        results: list = []
        jobs = T._build_jobs(
            self.manifest, self.resolved, None, results, "SECURE"
        )
        return jobs, results

    def test_no_capacity_yields_no_jobs(self):
        jobs, _ = self._plan()
        self.assertEqual(jobs, [])

    def test_no_capacity_still_records_a_skip(self):
        _, results = self._plan()
        self.assertEqual(len(results), 1)
        image, status = results[0][0], results[0][1]
        self.assertEqual(image, IMAGE)
        self.assertEqual(status, "SKIP")

    def test_skip_note_names_the_candidates(self):
        _, results = self._plan()
        note = results[0][2]
        self.assertIn("RTX A4000", note)
        self.assertIn("L4", note)

    def test_available_capacity_still_plans_jobs(self):
        """The guard must not fire on a healthy run."""
        config.GPU_CATALOG[0] = {
            **CATALOG[0], "cudaVersionsAvailable": ["12.8"],
        }
        jobs, results = self._plan()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(results, [])


class EmptyResultsAreNeverAPass(unittest.TestCase):
    """Backstop for any future planning gap, independent of ON_SKIP."""

    def _summary_exit_code(self, results, on_skip):
        with mock.patch.object(config, "ON_SKIP", on_skip), \
                mock.patch.object(T, "_emit_step_summary"), \
                mock.patch.object(T, "_write_results_json"), \
                mock.patch("builtins.print"):
            return T._print_summary(results)

    def test_zero_rows_fails_even_under_on_skip_pass(self):
        self.assertEqual(self._summary_exit_code([], "pass"), 1)

    def test_zero_rows_fails_under_on_skip_warn(self):
        self.assertEqual(self._summary_exit_code([], "warn"), 1)

    def test_recorded_skip_obeys_on_skip(self):
        rows = [(IMAGE, "SKIP", "no capacity", "L4", "", "", "SECURE")]
        self.assertEqual(self._summary_exit_code(rows, "fail"), 1)
        self.assertEqual(self._summary_exit_code(rows, "warn"), 0)
        self.assertEqual(self._summary_exit_code(rows, "pass"), 0)

    def test_a_pass_row_still_passes(self):
        rows = [(IMAGE, "PASS", "ok", "L4", "12.8", "", "SECURE")]
        self.assertEqual(self._summary_exit_code(rows, "fail"), 0)


if __name__ == "__main__":
    unittest.main()
