"""`test_ports` entries can name a path (FileBrowser's `/health`).

A merge once dropped it from both probes, so `/health` silently became a
`/` check that any login page passes.
"""

import unittest
from unittest import mock

from runpod_smoke import checks, config


class PortChecksKeepTheirPath(unittest.TestCase):
    def test_proxy_check_requests_the_path(self):
        with mock.patch.object(config, "PORT_PROXY_TIMEOUT", 0):
            _, out = checks.run_port_proxy_check("pod1", 8080, "/health")
        url = f"{config.proxy_url('pod1', 8080)}/health"
        self.assertEqual(out.splitlines()[0], f"GET {url}")

    def test_in_pod_check_probes_the_path(self):
        with mock.patch.object(checks, "port_check_command",
                               return_value="true") as build, \
             mock.patch.object(checks, "_ssh_command_prefix",
                               return_value=["true"]):
            checks.run_port_check(checks.SshEndpoint("h", 22), 8080, path="/health")
        self.assertEqual(build.call_args.args[2], "/health")


if __name__ == "__main__":
    unittest.main()
