"""The smoke harness's test_vllm: what the Pod gets, and what the checks accept.

runpod/vllm-openai starts vLLM only with VLLM_API_KEY and a model in the start
command, so a test Pod without either never serves :8000.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runpod_smoke import config, pod
from runpod_smoke import vllm as smoke_vllm

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / ".github/scripts/generate_test_manifest.py"


def created_body(group):
    with mock.patch.object(pod.api, "request", return_value=(200, {"id": "p1"})) as request:
        pod.create_pod("runpod/vllm-openai:test", "NVIDIA L4", "smoke", group=group,
                       test_ports=[config.VLLM_PORT], allowed_cuda_versions=["13.0"])
    return request.call_args.kwargs["body"]


class VllmPodBody(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(config.GROUP_TEST_VLLM, {"vllm": True}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_vllm_pods_get_a_key_a_model_and_the_port(self):
        body = created_body("vllm")
        self.assertEqual(body["env"]["VLLM_API_KEY"], config.VLLM_TEST_API_KEY)
        self.assertEqual(body["cmd"][0], config.VLLM_TEST_MODEL)
        self.assertIn("8000/http", body["ports"])
        self.assertIn("22/tcp", body["ports"])

    def test_other_pods_get_neither(self):
        body = created_body("base_gpu")
        self.assertNotIn("VLLM_API_KEY", body.get("env", {}))
        self.assertNotIn("cmd", body)


class FakeProxy:
    """Answers like the image: probes open, everything else needs the key."""

    def __init__(self, open_route=None):
        self.open_route = open_route

    def __call__(self, url, *, key=None, body=None, timeout=30):
        path = url.split(".proxy.runpod.net", 1)[1]
        if path in ("/health", "/metrics") or path == self.open_route:
            return 200, b"ok"
        if key != config.VLLM_TEST_API_KEY:
            return 401, b'{"error": "Unauthorized"}'
        if path == "/v1/chat/completions":
            reply = {"choices": [{"message": {"content": "Hello"}}]}
            return 200, json.dumps(reply).encode()
        return 200, b"{}"


class VllmChecks(unittest.TestCase):
    def run_check(self, check, proxy):
        with mock.patch.object(smoke_vllm, "_request", proxy):
            return check("pod1", lambda _line: None)

    def test_the_image_s_behaviour_passes(self):
        for check in (smoke_vllm.wait_for_vllm, smoke_vllm.check_vllm_auth,
                      smoke_vllm.check_vllm_completion):
            ok, detail = self.run_check(check, FakeProxy())
            self.assertTrue(ok, detail)

    def test_a_route_open_without_the_key_fails(self):
        for route in ("/invocations", "/tokenize", "/v1/models"):
            ok, detail = self.run_check(smoke_vllm.check_vllm_auth, FakeProxy(route))
            self.assertFalse(ok, route)
            self.assertIn(route, detail)

    def test_post_dwell_probe_wants_the_gate_still_closed(self):
        with mock.patch.object(smoke_vllm, "_request", FakeProxy()):
            self.assertTrue(smoke_vllm.probe_vllm_alive("pod1")[0])
        with mock.patch.object(smoke_vllm, "_request", FakeProxy("/v1/models")):
            self.assertFalse(smoke_vllm.probe_vllm_alive("pod1")[0])


class Manifest(unittest.TestCase):
    def test_flag_reaches_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.yaml"
            subprocess.run(
                [sys.executable, str(GENERATOR), "--profile", "gpu",
                 "--refs", json.dumps(["runpod/vllm-openai:1.0.0-vllmv0.33.0"]),
                 "--min-vram-gb", "24", "--manufacturer", "NVIDIA",
                 "--test-vllm", "--output", str(manifest)],
                capture_output=True, text=True, check=True,
            )
            self.assertIn("test_vllm: true", manifest.read_text())


if __name__ == "__main__":
    unittest.main()
