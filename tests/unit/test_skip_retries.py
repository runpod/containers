"""SKIP / UNVERIFIED jobs are re-run in-process instead of failing CI.

A SKIP means RunPod had no capacity on any candidate when we asked, which
says nothing about the image. Capacity frees up within minutes, so the
harness waits and re-runs just those jobs before ON_SKIP decides the exit
code — what people used to do by hand with "Re-run failed jobs".
"""

import unittest
from unittest import mock

import test_images as T
from runpod_smoke import config


def _job(img):
    return (img, "base_gpu", ["L4", "RTX A4000"], "", "SECURE")


class SkipRetries(unittest.TestCase):
    def _run(self, jobs, outcomes, retries=3, on_skip="fail"):
        """`outcomes` maps image -> list of statuses, one per attempt."""
        calls: list[str] = []

        def fake_test_image(img, *_a, **_k):
            calls.append(img)
            status = outcomes[img].pop(0)
            return status, f"note {status}", "L4", ""

        results: list = []
        with mock.patch.object(config, "SKIP_RETRIES", retries), \
                mock.patch.object(config, "SKIP_RETRY_DELAY", 7), \
                mock.patch.object(config, "ON_SKIP", on_skip), \
                mock.patch.object(config, "MAX_PARALLEL", 1), \
                mock.patch.object(T, "test_image", side_effect=fake_test_image), \
                mock.patch.object(T.time, "sleep") as sleep, \
                mock.patch("builtins.print"), \
                mock.patch.object(T, "log"):
            T._run_jobs(jobs, results)
        return results, calls, sleep

    def test_skip_then_pass_ends_as_pass(self):
        results, calls, sleep = self._run(
            [_job("a"), _job("b")],
            {"a": ["PASS"], "b": ["SKIP", "SKIP", "PASS"]},
        )
        self.assertEqual([r[1] for r in results], ["PASS", "PASS"])
        # Only the SKIPped job is re-run.
        self.assertEqual(calls, ["a", "b", "b", "b"])
        # Linear backoff: base delay x round.
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [7, 14])

    def test_fail_is_never_retried(self):
        results, calls, _ = self._run([_job("a")], {"a": ["FAIL"]})
        self.assertEqual(results[0][1], "FAIL")
        self.assertEqual(calls, ["a"])

    def test_gives_up_after_the_budget(self):
        results, calls, _ = self._run(
            [_job("a")], {"a": ["SKIP"] * 3}, retries=2,
        )
        self.assertEqual(results[0][1], "SKIP")
        self.assertEqual(len(calls), 3)

    def test_unverified_is_retried(self):
        results, _, _ = self._run([_job("a")], {"a": ["UNVERIFIED", "PASS"]})
        self.assertEqual(results[0][1], "PASS")

    def test_later_skip_does_not_downgrade_unverified(self):
        results, _, _ = self._run(
            [_job("a")], {"a": ["UNVERIFIED", "SKIP"]}, retries=1,
        )
        self.assertEqual(results[0][1], "UNVERIFIED")

    def test_fail_on_retry_wins(self):
        results, _, _ = self._run([_job("a")], {"a": ["SKIP", "FAIL"]})
        self.assertEqual(results[0][1], "FAIL")

    def test_no_retries_under_on_skip_pass(self):
        results, calls, sleep = self._run(
            [_job("a")], {"a": ["SKIP"]}, on_skip="pass",
        )
        self.assertEqual(results[0][1], "SKIP")
        self.assertEqual(calls, ["a"])
        sleep.assert_not_called()

    def test_parallel_keeps_job_order(self):
        def fake_test_image(img, *_a, **_k):
            return "PASS", "", "L4", ""

        jobs = [_job(str(i)) for i in range(6)]
        results: list = []
        with mock.patch.object(config, "MAX_PARALLEL", 3), \
                mock.patch.object(T, "test_image", side_effect=fake_test_image), \
                mock.patch("builtins.print"), \
                mock.patch.object(T, "log"):
            T._run_jobs(jobs, results)
        self.assertEqual([r[0] for r in results], [j[0] for j in jobs])


if __name__ == "__main__":
    unittest.main()
