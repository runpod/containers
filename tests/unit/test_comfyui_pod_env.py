"""The env the smoke harness gives ComfyUI test pods.

The ComfyUI image starts neither ComfyUI nor FileBrowser without a password,
and the ComfyUI workflow probes FileBrowser on 8080, so a ComfyUI test pod
needs both or its port checks fail with nothing listening.
"""

import unittest
from unittest import mock

from runpod_smoke import config, pod


def created_env(group):
    with mock.patch.object(pod.api, "request", return_value=(200, {"id": "p1"})) as request:
        pod.create_pod("runpod/comfyui:test", "NVIDIA A100", "smoke", group=group,
                       allowed_cuda_versions=["12.8"])
    return request.call_args.kwargs["body"].get("env", {})


class ComfyUIPodEnv(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(config.GROUP_TEST_COMFYUI, {"comfy": True}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_comfyui_pods_get_both_passwords(self):
        env = created_env("comfy")
        self.assertEqual(env["COMFYUI_PASSWORD"], config.COMFYUI_TEST_PASSWORD)
        self.assertEqual(env["FILEBROWSER_PASSWORD"], config.FILEBROWSER_TEST_PASSWORD)

    def test_other_pods_get_neither(self):
        env = created_env("base_gpu_only")
        self.assertNotIn("COMFYUI_PASSWORD", env)
        self.assertNotIn("FILEBROWSER_PASSWORD", env)

    def test_passwords_are_set(self):
        """start.sh leaves ComfyUI and FileBrowser off without a password."""
        for value in (config.COMFYUI_TEST_PASSWORD, config.FILEBROWSER_TEST_PASSWORD):
            self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
