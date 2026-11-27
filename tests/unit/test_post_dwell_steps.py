"""The post-dwell path runs on every image, so a name it cannot resolve
turns every smoke-test job red. Drives _check_pod to the end with the
dwell enabled, leaving the scan / dwell / post-dwell steps real.
"""

import contextlib
import unittest
from unittest import mock

from runpod_smoke import config, runner


class PostDwellSteps(unittest.TestCase):
    def _run(self, group="base_gpu", manager=False):
        """Returns (outcome, tails) where tails are the backfill windows
        the two log scans asked for, in order."""
        tails: list[int] = []

        def fake_scan(pod_id, tail=0):
            tails.append(tail)
            return True, "log scan passed"

        no_step = mock.Mock(return_value=None)
        with contextlib.ExitStack() as stack:
            def patch(name, **kw):
                stack.enter_context(mock.patch.object(runner, name, **kw))

            patch("wait_for_running",
                  return_value=("RUNNING", "ssh ok", object()))
            patch("pod_state", return_value={"cuda_version": "12.8"})
            patch("_set_host_cuda", new=mock.Mock())
            for step in (
                "_run_cuda_step", "_run_hygiene_steps", "_run_jupyter_steps",
                "_run_port_steps", "_run_comfyui_steps", "_run_vllm_steps",
            ):
                patch(step, new=no_step)
            patch("scan_pod_logs_for_errors", side_effect=fake_scan)
            patch("ssh_probe", return_value=(True, ""))
            patch("probe_comfyui_alive", return_value=(True, "HTTP 200"))
            patch("probe_vllm_alive", return_value=(True, "ok"))
            patch("dump_pod_logs", new=mock.Mock())
            patch("log", new=mock.Mock())
            stack.enter_context(mock.patch.object(runner.time, "sleep"))
            stack.enter_context(mock.patch.object(config, "DWELL_SEC", 60))
            stack.enter_context(
                mock.patch.object(config, "LOG_ERROR_SCAN", True))
            for group_map, value in (
                (config.GROUP_TEST_COMFYUI, manager),
                (config.GROUP_TEST_COMFYUI_FUNCTIONAL, False),
                (config.GROUP_TEST_COMFYUI_MANAGER, manager),
                (config.GROUP_TEST_VLLM, False),
            ):
                stack.enter_context(
                    mock.patch.dict(group_map, {group: value}, clear=True))
            outcome = runner._check_pod("pod1", "img:tag", group)
        return outcome, tails

    def test_dwell_path_completes(self):
        """A NameError here used to escape _check_pod and fail the job."""
        outcome, tails = self._run()
        self.assertEqual(outcome, ("PASS", ""))
        self.assertEqual(len(tails), 2)

    def test_default_window_without_the_manager_step(self):
        _, tails = self._run(manager=False)
        self.assertEqual(tails, [0, 0])

    def test_wider_window_on_both_scans_with_the_manager_step(self):
        """The widened window has to survive the dwell: the second scan
        reads the same log, by then longer."""
        _, tails = self._run(manager=True)
        self.assertEqual(
            tails,
            [config.LOG_API_TAIL_VERBOSE, config.LOG_API_TAIL_VERBOSE],
        )


if __name__ == "__main__":
    unittest.main()
