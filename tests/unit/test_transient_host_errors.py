"""Host-side hiccups must not read as a broken image.

Every case here failed a release.yml smoke job that then passed on re-run
with the same image (CON-2321). A FAIL is never retried, so each one cost a
wait for the whole workflow run before the job could be re-run by hand.
These are routed to a retry instead; a real image fault still fails.
"""

import subprocess
import unittest
from unittest import mock

from runpod_smoke import checks, runner
from runpod_smoke import vllm as smoke_vllm
from runpod_smoke.checks import PodDiagnostics


IMAGE = "runpod/burn-dev:1.0.0-rc.232-cuda1290-ubuntu2404"

PULL_REFUSED = (
    "error pulling image: Error response from daemon: Head \"https://registry-1"
    ".docker.io/v2/runpod/burn-dev/manifests/1.0.0-rc.232-cuda1290-ubuntu2404\""
    ": unauthorized: access token has insufficient scopes"
)
KEYRING_FULL = (
    "error starting container: Error response from daemon: failed to create "
    "task for container: failed to create shim task: OCI runtime create "
    "failed: runc create failed: unable to start container process: error "
    "during container init: unable to join session keyring: unable to create "
    "session key: disk quota exceeded: unknown"
)


def _proc(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class HostStartFailure(unittest.TestCase):
    def _classify(self, state, sys_lines):
        diagnostics = PodDiagnostics(list(sys_lines), [], list(sys_lines))
        with mock.patch.object(runner, "dump_pod_logs", return_value=diagnostics), \
                mock.patch.object(runner, "log"):
            return runner._classify_non_running(state, "detail", "pod1", IMAGE)

    def test_refused_private_image_pull_is_unverified(self):
        status, note = self._classify("TERMINAL", [PULL_REFUSED])
        self.assertEqual(status, "UNVERIFIED")
        self.assertIn("insufficient scopes", note)

    def test_host_out_of_keyrings_is_unverified_not_an_oci_fail(self):
        status, note = self._classify("TERMINAL", [KEYRING_FULL])
        self.assertEqual(status, "UNVERIFIED")
        self.assertIn("session key", note)

    def test_other_oci_errors_still_fail(self):
        status, _ = self._classify(
            "TERMINAL",
            ["OCI runtime create failed: exec: \"/start.sh\": permission denied"],
        )
        self.assertEqual(status, "FAIL")


class SshTransportRetry(unittest.TestCase):
    def _run(self, results):
        with mock.patch("subprocess.run", side_effect=results) as run, \
                mock.patch("runpod_smoke.checks.time.sleep"):
            out = checks._run_over_ssh(checks.SshEndpoint("1.2.3.4", 22), "true", timeout=30)
        return out, run.call_count

    def test_connect_timeout_is_retried(self):
        (r, notes), calls = self._run([
            _proc(255, stderr="ssh: connect to host 47.47.180.4 port 11713: "
                               "Connection timed out"),
            _proc(0, stdout="https fetch ok"),
        ])
        self.assertEqual((r.returncode, calls), (0, 2))
        self.assertIn("Connection timed out", notes[0])

    def test_proxy_refusing_the_key_is_retried(self):
        (r, _), calls = self._run([
            _proc(255, stderr="we4eyuzv7qi55t-64411b6e@ssh.runpod.io: "
                               "Permission denied (publickey)."),
            _proc(0),
        ])
        self.assertEqual((r.returncode, calls), (0, 2))

    def test_a_failing_check_is_not_retried(self):
        (r, notes), calls = self._run([_proc(1, stdout="FAIL: revoked CA present")])
        self.assertEqual((r.returncode, calls, notes), (1, 1, []))

    def test_remote_exit_255_without_an_ssh_error_is_not_retried(self):
        (r, _), calls = self._run([_proc(255, stdout="script exited 255")])
        self.assertEqual((r.returncode, calls), (255, 1))

    def test_gives_up_after_the_attempts(self):
        err = _proc(255, stderr="ssh: connect to host h port 1: Connection refused")
        (r, notes), calls = self._run([err, err, err])
        self.assertEqual((r.returncode, calls, len(notes)), (255, 3, 2))

    def test_simple_check_reports_the_retry(self):
        endpoint = checks.SshEndpoint("1.2.3.4", 22)
        with mock.patch("subprocess.run", side_effect=[
            _proc(255, stderr="ssh: connect to host 1.2.3.4 port 22: "
                               "Connection timed out"),
            _proc(0, stdout="CA trust store ok"),
        ]), mock.patch("runpod_smoke.checks.time.sleep"):
            ok, output = checks.run_simple_check(endpoint, "true")
        self.assertTrue(ok)
        self.assertIn("ssh failed to connect", output)
        self.assertIn("CA trust store ok", output)

    def test_proxy_session_refused_is_retried(self):
        """The proxy endpoint runs through a PTY session; a refused session
        comes back as ssh's own status and words, not a command result."""
        endpoint = checks.SshEndpoint(
            "ssh.runpod.io", 22, user="pod-64411b6e", pty=True,
        )
        with mock.patch.object(checks, "_run_pty", side_effect=[
            (255, "", "pod-64411b6e@ssh.runpod.io: Permission denied (publickey)."),
            (0, "ok\n__SMOKE_RC=0__\n", ""),
        ]) as pty, mock.patch.object(checks, "_pty_result",
                                     side_effect=[(None, ""), (0, "ok")]), \
                mock.patch("runpod_smoke.checks.time.sleep"):
            ok, output = checks.run_simple_check(endpoint, "true")
        self.assertTrue(ok)
        self.assertEqual(pty.call_count, 2)
        self.assertIn("Permission denied", output)


class DwellReProbe(unittest.TestCase):
    def _dwell(self, probes):
        endpoint = checks.SshEndpoint("1.2.3.4", 22)
        with mock.patch.object(runner, "ssh_probe", side_effect=probes) as probe, \
                mock.patch.object(runner, "dump_pod_logs"), \
                mock.patch.object(runner, "log"), \
                mock.patch.object(runner.time, "sleep"), \
                mock.patch.object(runner.config, "DWELL_SEC", 60), \
                mock.patch.object(runner.config, "DWELL_PROBE_ATTEMPTS", 3):
            return runner._run_dwell_step(endpoint, "pod1", IMAGE), probe.call_count

    def test_one_dropped_probe_is_not_a_crash(self):
        outcome, calls = self._dwell([(False, "ssh probe timed out"), (True, "")])
        self.assertIsNone(outcome)
        self.assertEqual(calls, 2)

    def test_a_crashed_container_still_fails(self):
        outcome, calls = self._dwell([(False, "ssh probe timed out")] * 3)
        self.assertEqual(outcome[0], "FAIL")
        self.assertIn("crashed after initial boot", outcome[1])
        self.assertEqual(calls, 3)


class LogScan(unittest.TestCase):
    def _scan(self, ok, report):
        with mock.patch.object(runner, "scan_pod_logs_for_errors",
                               return_value=(ok, report)), \
                mock.patch.object(runner, "dump_pod_logs"), \
                mock.patch.object(runner, "log"), \
                mock.patch.object(runner.config, "LOG_ERROR_SCAN", True):
            return runner._run_log_scan_step("pod1", IMAGE)

    def test_log_api_down_is_unverified(self):
        outcome = self._scan(False, "log scan UNVERIFIED — the log API returned "
                                    "no container logs after 3 attempts")
        self.assertEqual(outcome[0], "UNVERIFIED")

    def test_error_markers_still_fail(self):
        outcome = self._scan(False, "Traceback (most recent call last):")
        self.assertEqual(outcome[0], "FAIL")


class VllmPostDwellProbe(unittest.TestCase):
    def _probe(self, side_effect):
        with mock.patch.object(smoke_vllm, "_request", side_effect=side_effect), \
                mock.patch.object(smoke_vllm.time, "sleep"):
            return smoke_vllm.probe_vllm_alive("pod1")

    def test_one_proxy_timeout_is_retried(self):
        ok, _ = self._probe([
            TimeoutError("The read operation timed out"),
            (200, b""), (401, b""),
        ])
        self.assertTrue(ok)

    def test_an_opened_gate_is_not_retried(self):
        ok, detail = self._probe([(200, b""), (200, b"")])
        self.assertFalse(ok)
        self.assertIn("/v1/models without key 200", detail)

    def test_gives_up_after_the_attempts(self):
        ok, detail = self._probe([TimeoutError("timed out")] * 3)
        self.assertFalse(ok)
        self.assertIn("3 attempt(s)", detail)


if __name__ == "__main__":
    unittest.main()
