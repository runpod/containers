"""`/api/status` cannot tell you whether JupyterLab actually renders.

It is served by a plain handler, so it answers 200 even when every
StaticFileHandler route 500s and the user sees a blank page. That is exactly
what shipped in runpod/base 1.3.1 and runpod/comfyui 1.3.1: tornado 6.5.9
against jupyter_server 2.21.0 raised AttributeError on
`allowed_symlink_directory` for every `/static/...` request, and the smoke
test passed anyway (tornadoweb/tornado#3724).
"""

import io
import unittest
import urllib.error
from unittest import mock

from runpod_smoke.checks import run_jupyter_static_check


POD = "abc123"


def _response(status, content_type):
    resp = mock.MagicMock()
    resp.status = status
    resp.headers = {"Content-Type": content_type}
    resp.__enter__.return_value = resp
    return resp


class JupyterStaticCheck(unittest.TestCase):
    def test_served_asset_passes(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_response(200, "image/x-icon")):
            ok, log = run_jupyter_static_check(POD)
        self.assertTrue(ok)
        self.assertIn("HTTP 200", log)

    def test_500_from_the_tornado_659_regression_fails(self):
        err = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, io.BytesIO(b"")
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            ok, log = run_jupyter_static_check(POD)
        self.assertFalse(ok)
        self.assertIn("500", log)

    def test_login_page_redirect_is_not_a_pass(self):
        """A 200 carrying HTML means we were bounced to the login page, not
        handed the asset."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_response(200, "text/html; charset=UTF-8")):
            ok, _ = run_jupyter_static_check(POD)
        self.assertFalse(ok)

    def test_unreachable_proxy_fails(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            ok, log = run_jupyter_static_check(POD)
        self.assertFalse(ok)
        self.assertIn("TimeoutError", log)


if __name__ == "__main__":
    unittest.main()
