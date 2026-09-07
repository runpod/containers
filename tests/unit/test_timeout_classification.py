"""A readiness timeout must not be blamed on the host by default.

Two deterministic image faults look exactly like a slow host from the
outside — no SSH, no RUNNING, no terminal status:

  * the NVIDIA prestart hook refusing the container, and
  * a container that cannot start at all.

Both used to be reported as STUCK, which retries elsewhere and ends the
image as SKIP. With `on-skip: warn` on the release gates that keeps CI
green, so a broken image could ship. What remains genuinely ambiguous is
reported as UNVERIFIED rather than guessed either way.
"""

import unittest
from unittest import mock

from runpod_smoke import config, runner
from runpod_smoke.checks import PodDiagnostics, container_startup_failure


IMAGE = "runpod/pytorch:1.2.0-cu1300-torch2130-ubuntu2404"


class StartupFailureDetection(unittest.TestCase):
    def test_detects_unexecutable_entrypoint(self):
        self.assertTrue(container_startup_failure([
            "standard_init_linux.go:228: exec user process caused: exec format error",
        ]))

    def test_detects_missing_entrypoint(self):
        self.assertTrue(container_startup_failure([
            'exec: "/start.sh": no such file or directory',
        ]))

    def test_detects_oci_refusal(self):
        self.assertTrue(container_startup_failure([
            "OCI runtime create failed: container_linux.go:380",
        ]))

    def test_detects_oom_kill(self):
        self.assertTrue(container_startup_failure([
            "Out of memory: Killed process 1234 (python3)",
        ]))

    def test_ignores_ordinary_boot_chatter(self):
        self.assertFalse(container_startup_failure([
            "start.sh: starting JupyterLab on 8888",
            "Server listening on 0.0.0.0 port 22.",
            "[ComfyUI-Manager] All startup tasks have been completed.",
            "warning: no such file or directory found in cache, rebuilding",
            "executing: pip install foo (package not found upstream)",
        ]))

    def test_a_python_traceback_alone_is_not_a_startup_failure(self):
        """ComfyUI-Manager prints these for a failing custom node while
        ComfyUI itself comes up fine. Only a slow host would then turn the
        pod into a FAIL instead of a retry."""
        self.assertFalse(container_startup_failure([
            "Traceback (most recent call last):",
            '  File "/opt/ComfyUI/custom_nodes/x/__init__.py", line 3',
            "ModuleNotFoundError: No module named 'x'",
        ]))

    def test_empty_and_none_are_not_failures(self):
        self.assertFalse(container_startup_failure([]))
        self.assertFalse(container_startup_failure(None))


class Classification(unittest.TestCase):
    def _classify(self, state, sys_errors=(), container_lines=()):
        diagnostics = PodDiagnostics(list(sys_errors), list(container_lines))
        with mock.patch.object(runner, "dump_pod_logs", return_value=diagnostics), \
                mock.patch.object(runner, "log"):
            return runner._classify_non_running(state, "detail", "pod1", IMAGE)

    def test_no_endpoint_is_infrastructure(self):
        status, _ = self._classify("TIMEOUT_NO_ENDPOINT")
        self.assertEqual(status, "STUCK")

    def test_assigned_but_silent_is_unverified_not_stuck(self):
        status, note = self._classify("TIMEOUT_UNREACHABLE")
        self.assertEqual(status, "UNVERIFIED")
        self.assertTrue(note)

    def test_startup_failure_wins_over_the_timeout_kind(self):
        """Deterministic, so it must not be retried as a host problem."""
        for state in ("TIMEOUT_NO_ENDPOINT", "TIMEOUT_UNREACHABLE"):
            status, note = self._classify(
                state, container_lines=["exec format error"]
            )
            self.assertEqual(status, "FAIL", state)
            self.assertIn("failed to start", note)

    def test_init_rejection_still_wins(self):
        status, note = self._classify(
            "TIMEOUT_NO_ENDPOINT",
            sys_errors=[
                "nvidia-container-cli: requirement error: unsatisfied "
                "condition: cuda>=13.0",
            ],
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("cuda>=13.0", note)

    def test_terminal_state_is_still_a_fail(self):
        status, _ = self._classify("TERMINAL")
        self.assertEqual(status, "FAIL")


class UnverifiedIsNotACapacityGap(unittest.TestCase):
    def _summary_exit_code(self, status, on_skip):
        import test_images as T
        rows = [(IMAGE, status, "note", "RTX 5080", "", "", "SECURE")]
        with mock.patch.object(config, "ON_SKIP", on_skip), \
                mock.patch.object(T, "_emit_step_summary"), \
                mock.patch.object(T, "_write_results_json"), \
                mock.patch("builtins.print"):
            return T._print_summary(rows)

    def test_unverified_is_fatal_on_the_release_gates(self):
        """base / rocm / comfyui run with on-skip: warn."""
        self.assertEqual(self._summary_exit_code("UNVERIFIED", "warn"), 1)
        self.assertEqual(self._summary_exit_code("UNVERIFIED", "fail"), 1)

    def test_unverified_is_tolerated_by_the_catalog_sweep(self):
        """gpu-compatibility.yml runs with on-skip: pass by design."""
        self.assertEqual(self._summary_exit_code("UNVERIFIED", "pass"), 0)

    def test_a_skip_is_still_only_a_capacity_gap(self):
        self.assertEqual(self._summary_exit_code("SKIP", "warn"), 0)


class Aggregation(unittest.TestCase):
    """`test_image` must not file an unverified image under "no capacity"."""

    def _run(self, per_instance):
        calls = iter(per_instance)
        with mock.patch.object(runner, "test_pair", lambda *a, **k: next(calls)), \
                mock.patch.object(runner, "log"), \
                mock.patch.object(runner, "set_worker_context"):
            return runner.test_image(
                IMAGE, ["RTX 5080", "RTX 5090"], "base_gpu", "", "SECURE"
            )

    def test_unverified_outranks_unavailable(self):
        status, note, insts, _ = self._run([
            ("UNVERIFIED", "endpoint never answered"),
            ("UNAVAILABLE", ""),
        ])
        self.assertEqual(status, "UNVERIFIED")
        self.assertIn("RTX 5080", insts)
        self.assertIn("never answered", note)

    def test_unverified_outranks_stuck(self):
        status, _, _, _ = self._run([
            ("STUCK", ""),
            ("UNVERIFIED", "endpoint never answered"),
        ])
        self.assertEqual(status, "UNVERIFIED")

    def test_a_pass_still_wins(self):
        status, _, inst, _ = self._run([
            ("UNVERIFIED", "endpoint never answered"),
            ("PASS", ""),
        ])
        self.assertEqual(status, "PASS")
        self.assertEqual(inst, "RTX 5090")

    def test_all_stuck_is_still_a_skip(self):
        status, _, _, _ = self._run([("STUCK", ""), ("STUCK", "")])
        self.assertEqual(status, "SKIP")


if __name__ == "__main__":
    unittest.main()
