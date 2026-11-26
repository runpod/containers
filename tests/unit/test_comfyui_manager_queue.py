"""Manager's POST /v2/manager/queue/task snapshots the system inside the
request handler (a git fetch plus `pip freeze`), so it can take minutes. A
read timeout there used to escape the runner and kill the whole job.
"""

import json
import unittest
from unittest import mock

from runpod_smoke import comfyui, config


NODE = {"id": "comfyui-depthanythingv2", "selected_version": "1.0.2",
        "verify_class": "DepthAnything_V2"}


class _FakeClock:
    """comfyui.py reads the clock through the `time` module, so a stub here
    makes the deadline loops finish instantly instead of spinning."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def time(self):
        return 1700000000.0 + self.now


def _status(done=0, total=0, processing=False):
    return json.dumps({
        "done_count": done, "total_count": total, "is_processing": processing,
    }).encode()


class QueueTaskTimeout(unittest.TestCase):
    def _install(self, responses):
        """`responses` maps a URL fragment to a list of results, each either
        an exception to raise or a (code, body) pair."""
        posted: list[str] = []

        def fake_request(url, data=None, timeout=30, authenticated=True):
            for fragment, queue in responses.items():
                if fragment in url:
                    posted.append(fragment)
                    result = queue.pop(0) if len(queue) > 1 else queue[0]
                    if isinstance(result, Exception):
                        raise result
                    return result
            raise AssertionError(f"unexpected request to {url}")

        with mock.patch.object(comfyui, "_request", side_effect=fake_request), \
                mock.patch.object(comfyui, "time", _FakeClock()), \
                mock.patch.object(config, "COMFYUI_MANAGER_QUEUE_TIMEOUT", 30), \
                mock.patch.object(config, "COMFYUI_MANAGER_INSTALL_TIMEOUT", 30):
            ok, detail = comfyui._manager_install_node(
                "http://pod", NODE, lambda _line: None)
        return ok, detail, posted

    def test_timeout_does_not_escape(self):
        """The whole point: a read timeout is an outcome, not an exception."""
        ok, detail, _ = self._install({
            "queue/task": [TimeoutError("The read operation timed out")],
            "queue/status": [(200, _status())],
        })
        self.assertFalse(ok)
        self.assertTrue(detail.startswith(comfyui.MANAGER_UNVERIFIED), detail)

    def test_timed_out_task_is_not_posted_twice(self):
        """The handler queues the task after the slow part, so a timeout does
        not mean it was lost. A second POST would install the node twice."""
        ok, detail, posted = self._install({
            "queue/task": [TimeoutError("timed out")],
            # First poll finds our task pending, then it drains.
            "queue/status": [(200, _status(total=1, processing=True)),
                             (200, _status(done=1))],
            "queue/start": [(200, b"")],
        })
        self.assertTrue(ok, detail)
        self.assertEqual(posted.count("queue/task"), 1)

    def test_queue_start_is_retried(self):
        """queue/start is idempotent (200 started / 201 already running)."""
        ok, detail, posted = self._install({
            "queue/task": [(200, b"")],
            "queue/start": [TimeoutError("timed out"), (201, b"")],
            "queue/status": [(200, _status(done=1))],
        })
        self.assertTrue(ok, detail)
        self.assertEqual(posted.count("queue/start"), 2)

    def test_queue_start_never_answering_is_unverified(self):
        ok, detail, posted = self._install({
            "queue/task": [(200, b"")],
            "queue/start": [TimeoutError("timed out")],
        })
        self.assertFalse(ok)
        self.assertTrue(detail.startswith(comfyui.MANAGER_UNVERIFIED), detail)
        self.assertEqual(posted.count("queue/start"), 3)

    def test_http_error_is_still_a_failure(self):
        """A 400 from the Manager is our bug, not a flaky network."""
        ok, detail, _ = self._install({
            "queue/task": [(400, b"Invalid task data")],
        })
        self.assertFalse(ok)
        self.assertFalse(detail.startswith(comfyui.MANAGER_UNVERIFIED))
        self.assertIn("400", detail)


class RegistryBlame(unittest.TestCase):
    def test_network_error_in_history_reads_as_registry(self):
        body = json.dumps([{
            "ui_id": "smoke-1", "status": {"status_str": "error"},
            "result": "Failed to download: Max retries exceeded with url "
                      "(Caused by NewConnectionError) api.comfy.org",
        }]).encode()
        self.assertTrue(comfyui._history_blames_the_registry(body))

    def test_compact_json_still_matches(self):
        """The Manager's serializer decides the spacing, so do not rely on it."""
        body = (b'[{"status_str":"error","result":"max retries exceeded '
                b'with url: api.comfy.org"}]')
        self.assertTrue(comfyui._history_blames_the_registry(body))

    def test_dependency_error_does_not(self):
        body = json.dumps([{
            "ui_id": "smoke-1", "status": {"status_str": "error"},
            "result": "ERROR: Cannot install depthanything because these "
                      "package versions have conflicting dependencies.",
        }]).encode()
        self.assertFalse(comfyui._history_blames_the_registry(body))

    def test_success_never_blames_the_registry(self):
        body = json.dumps([{
            "ui_id": "smoke-1", "status": {"status_str": "success"},
            "result": "connection reused from api.comfy.org",
        }]).encode()
        self.assertFalse(comfyui._history_blames_the_registry(body))

    def test_missing_history_does_not(self):
        self.assertFalse(comfyui._history_blames_the_registry(None))


class RunnerOutcome(unittest.TestCase):
    """An unreachable pod must not be filed as a broken image: UNVERIFIED
    moves on to the next instance, FAIL stops the whole image."""

    def _steps(self, result):
        from runpod_smoke import runner

        with mock.patch.object(runner, "run_comfyui_manager_check",
                               return_value=result), \
                mock.patch.object(runner, "_check_port_proxy_first",
                                  return_value=None), \
                mock.patch.object(runner, "check_comfyui_refuses_anonymous",
                                  return_value=(True, "401")), \
                mock.patch.object(runner, "check_filebrowser_requires_password",
                                  return_value=(True, "401")), \
                mock.patch.object(runner, "comfyui_auth_headers",
                                  return_value={}), \
                mock.patch.object(runner, "dump_pod_logs"), \
                mock.patch.object(runner, "log"), \
                mock.patch.dict(config.GROUP_TEST_COMFYUI,
                                {"g": True}, clear=True), \
                mock.patch.dict(config.GROUP_TEST_COMFYUI_FUNCTIONAL,
                                {"g": False}, clear=True), \
                mock.patch.dict(config.GROUP_TEST_COMFYUI_MANAGER,
                                {"g": True}, clear=True):
            return runner._run_comfyui_steps(object(), "pod1", "img:tag", "g")

    def test_marker_becomes_unverified(self):
        outcome = self._steps(
            (False, f"{comfyui.MANAGER_UNVERIFIED}: queue/task never answered"))
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome[0], "UNVERIFIED")

    def test_real_failure_stays_fail(self):
        outcome = self._steps((False, "node class DepthAnything_V2 not available"))
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome[0], "FAIL")

    def test_pass_returns_no_outcome(self):
        self.assertIsNone(self._steps((True, "installed")))


if __name__ == "__main__":
    unittest.main()
