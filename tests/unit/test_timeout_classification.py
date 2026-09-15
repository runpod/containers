"""Who a readiness timeout belongs to: the image, or RunPod.

Nothing visible from outside separates them. `status` reads `RUNNING` from
scheduling time onward, so a pod still downloading a 50GB image, a pod whose
entrypoint cannot execute, and a pod RunPod never routed to all look
identical: no SSH, status RUNNING, no terminal state.

The verdict therefore comes from evidence, and getting it wrong is expensive
in both directions — blaming RunPod hides a broken image behind
`on-skip: warn`, and blaming the image fails a release over a platform
hiccup. What stays genuinely ambiguous is reported as UNVERIFIED rather than
guessed either way.
"""

import unittest
from unittest import mock

from runpod_smoke import checks, config, pod, runner
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
    def _classify(self, state, sys_errors=(), container_lines=(), sys_lines=None):
        diagnostics = PodDiagnostics(
            list(sys_errors),
            list(container_lines),
            list(sys_errors) if sys_lines is None else list(sys_lines),
        )
        with mock.patch.object(runner, "dump_pod_logs", return_value=diagnostics), \
                mock.patch.object(runner, "log"):
            return runner._classify_non_running(state, "detail", "pod1", IMAGE)

    def test_no_endpoint_is_infrastructure(self):
        status, _ = self._classify("TIMEOUT_INFRA")
        self.assertEqual(status, "STUCK")

    def test_assigned_but_silent_is_unverified_not_stuck(self):
        status, note = self._classify("TIMEOUT_UNREACHABLE")
        self.assertEqual(status, "UNVERIFIED")
        self.assertTrue(note)

    def test_startup_failure_wins_over_the_timeout_kind(self):
        """Deterministic, so it must not be retried as a host problem."""
        for state in ("TIMEOUT_INFRA", "TIMEOUT_UNREACHABLE"):
            status, note = self._classify(
                state, container_lines=["exec format error"]
            )
            self.assertEqual(status, "FAIL", state)
            self.assertIn("failed to start", note)

    def test_init_rejection_still_wins(self):
        status, note = self._classify(
            "TIMEOUT_INFRA",
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


class StartupFailureVisibleOnlyInTheSystemLog(unittest.TestCase):
    """A container that could not be created never wrote a line of its own.

    Its only trace is RunPod's system log, so scanning the container stream
    alone reported these as STUCK — which retries, ends as SKIP, and passes
    under `on-skip: warn`. A broken entrypoint could ship.
    """

    def _classify(self, sys_lines, container_lines=()):
        diagnostics = PodDiagnostics(
            checks.filter_sys_errors(list(sys_lines)),
            list(container_lines),
            list(sys_lines),
        )
        with mock.patch.object(runner, "dump_pod_logs", return_value=diagnostics), \
                mock.patch.object(runner, "log"):
            return runner._classify_non_running(
                "TIMEOUT_INFRA", "detail", "pod1", IMAGE
            )

    def test_oci_error_with_no_container_output(self):
        status, note = self._classify(
            ["OCI runtime create failed: container_linux.go:380"]
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("failed to start", note)

    def test_markers_the_display_filter_drops_are_still_caught(self):
        """`SYS_LOG_ERROR_PATTERN` only matches error/fail/crash wording, so
        these never reach `sys_errors` — classifying from that subset would
        miss them even once both streams are consulted."""
        for line in (
            'exec: "/start.sh": no such file or directory',
            "permission denied while trying to run /start.sh entrypoint",
            "Out of memory: Killed process 1234 (python3)",
        ):
            self.assertEqual(checks.filter_sys_errors([line]), [], line)
            status, _ = self._classify([line])
            self.assertEqual(status, "FAIL", line)

    def test_ordinary_system_log_still_retries(self):
        """The guard must not turn every timeout into a FAIL."""
        status, _ = self._classify([
            "be7707169180 Extracting [>       ] 163.8kB/13.31MB",
            "Status: Downloaded newer image for runpod/pytorch:x",
            "create container runpod/pytorch:x",
            "start container for runpod/pytorch:x: begin",
        ])
        self.assertEqual(status, "STUCK")


# Verbatim from the container log of a real MI300X pod that RunPod never
# gave a public port for 22/tcp. sshd is up; only the path to it is missing.
ROCM_LOG_SSHD_UP = [
    "Starting Nginx service...",
    " * Starting nginx nginx",
    "Pod Started",
    "Setting up SSH...",
    "RSA key fingerprint:",
    " * Starting OpenBSD Secure Shell server sshd",
    "   ...done.",
    "Exporting environment variables...",
    "Start script(s) finished, Pod is ready to use.",
]


class ContainerProgressFromItsOwnLog(unittest.TestCase):
    """`status` is RUNNING from scheduling time onward, so the container's
    log stream is the only thing that says how far it actually got."""

    def _progress(self, lines):
        with mock.patch.object(checks, "fetch_pod_logs_api", return_value=lines):
            return checks.container_progress("pod1")

    def test_empty_log_means_still_pulling(self):
        self.assertEqual(self._progress([]), (False, False))

    def test_output_without_sshd_means_started_only(self):
        self.assertEqual(
            self._progress(["Starting Nginx service...", "Pod Started"]),
            (True, False),
        )

    def test_real_rocm_log_shows_sshd_up(self):
        self.assertEqual(self._progress(ROCM_LOG_SSHD_UP), (True, True))

    def test_foreground_sshd_is_recognised(self):
        self.assertTrue(
            self._progress(["Server listening on 0.0.0.0 port 22."]).sshd_up
        )

    def test_unreachable_log_api_is_none(self):
        self.assertIsNone(self._progress(None))


# Verbatim from a RunPod system log, mid-pull and then at hand-off. This is
# the authoritative answer to "has the image even finished downloading",
# which the container's own log can only hint at and `status` cannot answer.
SYSLOG_PULLING = [
    "ab6fdd207dfd Extracting [=========>]  205B/205B",
    "ab6fdd207dfd Pull complete",
    "be7707169180 Extracting [>       ]  163.8kB/13.31MB",
]
SYSLOG_HANDED_OFF = SYSLOG_PULLING + [
    "Digest: sha256:ce5e842ca0c7233a983ff76a83739b445172259c77a43a117453ef7e6a64d0b7",
    "Status: Downloaded newer image for runpod/comfyui:1.4.6-cuda12.8",
    "create container runpod/comfyui:1.4.6-cuda12.8",
    "1.4.6-cuda12.8 Pulling from runpod/comfyui",
    "Status: Image is up to date for runpod/comfyui:1.4.6-cuda12.8",
    "start container for runpod/comfyui:1.4.6-cuda12.8: begin",
]


class PodStageFromTheSystemLog(unittest.TestCase):
    def _stage(self, lines):
        with mock.patch.object(checks, "fetch_pod_logs_api", return_value=lines):
            return checks.pod_stage("pod1")

    def test_mid_pull(self):
        stage = self._stage(SYSLOG_PULLING)
        self.assertTrue(stage.pulling)
        self.assertFalse(stage.pull_done)
        self.assertFalse(stage.container_started)
        self.assertEqual(stage.label, "still pulling the image")

    def test_handed_off_to_the_container(self):
        stage = self._stage(SYSLOG_HANDED_OFF)
        self.assertTrue(stage.pull_done)
        self.assertTrue(stage.container_started)
        self.assertEqual(stage.label, "container started")

    def test_nothing_logged_yet(self):
        stage = self._stage([])
        self.assertEqual(stage.label, "no pull or start activity logged yet")

    def test_unreachable_log_api_is_none(self):
        self.assertIsNone(self._stage(None))


class WhoIsToBlameForATimeout(unittest.TestCase):
    def _wait_timeout(self, progress, stage=None):
        """Drive wait_for_running to its deadline with an assigned endpoint."""
        state = {
            "status": "RUNNING",           # set at scheduling time, not readiness
            "ssh_ip": "1.2.3.4", "ssh_port": 40022,
            "proxy_host": "", "proxy_port": 0, "proxy_user": "",
            "proxy_command": "",
        }
        # A short deadline with no sleep: the loop runs, sees the endpoint,
        # gets a refused probe, and falls through to the timeout verdict.
        with mock.patch.object(config, "CREATE_TIMEOUT", 0.05), \
                mock.patch.object(config, "POLL_INTERVAL", 0), \
                mock.patch.object(pod, "pod_state", return_value=state), \
                mock.patch.object(pod, "ssh_probe", return_value=(False, "refused")), \
                mock.patch.object(pod, "container_progress", return_value=progress), \
                mock.patch.object(pod, "pod_stage", return_value=stage), \
                mock.patch.object(pod, "_log_system_errors"), \
                mock.patch.object(pod, "log"):
            return pod.wait_for_running("pod1")

    def test_mid_pull_is_infra(self):
        outcome, detail, endpoint = self._wait_timeout(
            checks.ContainerProgress(started=False, sshd_up=False)
        )
        self.assertEqual(outcome, "TIMEOUT_INFRA")
        self.assertIn("still being pulled", detail)
        self.assertIsNone(endpoint)

    def test_sshd_up_but_unreachable_is_infra_not_unverified(self):
        """The MI300X case: the image did its part, RunPod never built a
        path to it. Blaming the image for that is a false red build."""
        outcome, detail, _ = self._wait_timeout(
            checks.ContainerProgress(started=True, sshd_up=True)
        )
        self.assertEqual(outcome, "TIMEOUT_INFRA")
        self.assertIn("brought sshd up", detail)

    def test_running_without_sshd_stays_unverified(self):
        outcome, detail, _ = self._wait_timeout(
            checks.ContainerProgress(started=True, sshd_up=False)
        )
        self.assertEqual(outcome, "TIMEOUT_UNREACHABLE")
        self.assertIn("never announced sshd", detail)

    def test_unreadable_log_stays_unverified(self):
        outcome, _, _ = self._wait_timeout(None)
        self.assertEqual(outcome, "TIMEOUT_UNREACHABLE")

    def test_system_log_mid_pull_wins_over_the_container_log(self):
        """The system log is authoritative on "has it even downloaded".
        Even a container log that looks started must not override it."""
        outcome, detail, _ = self._wait_timeout(
            checks.ContainerProgress(started=True, sshd_up=True),
            stage=checks.PodStage(
                pulling=True, pull_done=False, container_started=False
            ),
        )
        self.assertEqual(outcome, "TIMEOUT_INFRA")
        self.assertIn("still pulling the image", detail)

    def test_handed_off_falls_through_to_the_container_log(self):
        outcome, detail, _ = self._wait_timeout(
            checks.ContainerProgress(started=True, sshd_up=False),
            stage=checks.PodStage(
                pulling=True, pull_done=True, container_started=True
            ),
        )
        self.assertEqual(outcome, "TIMEOUT_UNREACHABLE")
        self.assertIn("never announced sshd", detail)

    def test_both_logs_unreadable_is_unverified(self):
        outcome, detail, _ = self._wait_timeout(None, stage=None)
        self.assertEqual(outcome, "TIMEOUT_UNREACHABLE")
        self.assertIn("neither log stream", detail)

    def test_infra_classifies_as_stuck_end_to_end(self):
        """So it retries on another host instead of going red."""
        diagnostics = PodDiagnostics([], [])
        with mock.patch.object(runner, "dump_pod_logs", return_value=diagnostics), \
                mock.patch.object(runner, "log"):
            status, _ = runner._classify_non_running(
                "TIMEOUT_INFRA", "brought sshd up", "pod1", IMAGE
            )
        self.assertEqual(status, "STUCK")



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
