"""The smoke harness's FileBrowser check on ComfyUI test pods.

FileBrowser is public on 8080 and test_ports only proves something answers
there, so this check is what fails when it serves /workspace without the pod's
FILEBROWSER_PASSWORD.
"""

import unittest
from unittest import mock

from runpod_smoke import comfyui, config

SESSION = "filebrowser_quantum_jwt=token"


class FakeFileBrowser:
    """Answers like Quantum behind the proxy; each flag breaks one rule."""

    def __init__(self, open_listing=False, accept_any=False, no_cookie=False):
        self.open_listing = open_listing
        self.accept_any = accept_any
        self.no_cookie = no_cookie

    def __call__(self, url, method="GET", headers=None, timeout=20):
        headers = headers or {}
        path = url.split(".proxy.runpod.net", 1)[1]
        if path.startswith("/api/auth/login"):
            password = headers.get("X-Password")
            if self.accept_any or password == config.FILEBROWSER_TEST_PASSWORD:
                cookies = [] if self.no_cookie else [SESSION + "; Path=/; HttpOnly"]
                return 200, cookies
            return 401, []
        if path.startswith("/api/resources"):
            if self.open_listing or headers.get("Cookie") == SESSION:
                return 200, []
            return 401, []
        return 404, []


class FileBrowserCheck(unittest.TestCase):
    def run_check(self, fake):
        with mock.patch.object(comfyui, "_filebrowser_request", fake):
            return comfyui.check_filebrowser_requires_password("pod1")

    def test_the_image_s_behaviour_passes(self):
        ok, detail = self.run_check(FakeFileBrowser())
        self.assertTrue(ok, detail)
        self.assertIn("GET /api/resources, session: HTTP 200", detail)

    def test_a_listing_without_a_session_fails(self):
        ok, detail = self.run_check(FakeFileBrowser(open_listing=True))
        self.assertFalse(ok)
        self.assertIn("no session: HTTP 200", detail)

    def test_a_login_with_any_password_fails(self):
        ok, detail = self.run_check(FakeFileBrowser(accept_any=True))
        self.assertFalse(ok)
        self.assertIn("wrong password: HTTP 200", detail)

    def test_a_login_without_a_cookie_fails(self):
        ok, detail = self.run_check(FakeFileBrowser(no_cookie=True))
        self.assertFalse(ok)
        self.assertIn("no session cookie", detail)

    def test_filebrowser_down_fails(self):
        ok, detail = self.run_check(lambda *_args, **_kwargs: (502, []))
        self.assertFalse(ok)
        self.assertIn("HTTP 502", detail)

    def test_it_targets_the_filebrowser_port(self):
        fake = mock.Mock(wraps=FakeFileBrowser())
        self.run_check(fake)
        for call in fake.call_args_list:
            self.assertIn(f"pod1-{config.FILEBROWSER_PORT}.proxy.runpod.net", call.args[0])


if __name__ == "__main__":
    unittest.main()
