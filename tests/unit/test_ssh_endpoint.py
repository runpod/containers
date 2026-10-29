"""Endpoints must be carried by value, never looked up by (host, port).

Every pod's SSH proxy answers at the same `ssh.runpod.io:22` and is told
apart only by the routing token in `username`. A registry keyed on address
is therefore one global slot: with two proxy-only pods in flight the second
registration wins, the first pod's checks connect to the second pod, and
they succeed — the address they reached is a live pod. Silent wrong-pod
results, not a crash.
"""

import shutil
import sys
import unittest
from unittest import mock

from runpod_smoke import checks
from runpod_smoke.checks import SshEndpoint, _ssh_command_prefix


PROXY_HOST = "ssh.runpod.io"


def _target(endpoint: SshEndpoint) -> str:
    """The `user@host` argv element `ssh` would connect to."""
    return _ssh_command_prefix(endpoint)[-1]


class TwoPodsOnTheSameProxy(unittest.TestCase):
    def setUp(self) -> None:
        self.pod_a = SshEndpoint(
            PROXY_HOST, 22, "pod-aaa-1111",
            "ssh pod-aaa-1111@ssh.runpod.io -i ~/.ssh/id_ed25519", pty=True,
        )
        self.pod_b = SshEndpoint(
            PROXY_HOST, 22, "pod-bbb-2222",
            "ssh pod-bbb-2222@ssh.runpod.io -i ~/.ssh/id_ed25519", pty=True,
        )

    def test_same_address_different_pod_keeps_its_own_login(self):
        self.assertEqual(self.pod_a.host, self.pod_b.host)
        self.assertEqual(self.pod_a.port, self.pod_b.port)
        self.assertEqual(_target(self.pod_a), f"pod-aaa-1111@{PROXY_HOST}")
        self.assertEqual(_target(self.pod_b), f"pod-bbb-2222@{PROXY_HOST}")

    def test_building_one_command_cannot_affect_the_other(self):
        """Interleaved, the way parallel workers actually call this."""
        before = _target(self.pod_a)
        _target(self.pod_b)
        self.assertEqual(_target(self.pod_a), before)

    def test_endpoints_are_distinct_dict_keys(self):
        """`wait_for_running` dedups its log lines per endpoint."""
        self.assertNotEqual(self.pod_a, self.pod_b)
        self.assertEqual(len({self.pod_a, self.pod_b}), 2)


class CommandConstruction(unittest.TestCase):
    def test_api_command_target_wins_over_user_at_host(self):
        """The proxy target is opaque; trust the API's own invocation."""
        endpoint = SshEndpoint(
            PROXY_HOST, 22, "ignored",
            "ssh real-token@ssh.runpod.io -i ~/.ssh/id_ed25519", pty=True,
        )
        self.assertEqual(_target(endpoint), f"real-token@{PROXY_HOST}")

    def test_pty_is_forced_with_double_t(self):
        """-t alone declines to allocate a tty when stdin is a pipe."""
        argv = _ssh_command_prefix(SshEndpoint(PROXY_HOST, 22, "tok", pty=True))
        self.assertIn("-tt", argv)

    def test_direct_endpoint_is_plain_root_with_a_port(self):
        argv = _ssh_command_prefix(SshEndpoint("38.65.239.56", 40022))
        self.assertNotIn("-tt", argv)
        self.assertEqual(argv[-1], "root@38.65.239.56")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("-p") + 1], "40022")

    def test_port_22_is_not_passed_explicitly(self):
        self.assertNotIn("-p", _ssh_command_prefix(SshEndpoint(PROXY_HOST, 22, "t")))

    def test_falsy_when_unassigned(self):
        self.assertFalse(SshEndpoint("", 0))
        self.assertFalse(SshEndpoint("host", 0))
        self.assertTrue(SshEndpoint("host", 22))


if __name__ == "__main__":
    unittest.main()


# A stand-in for RunPod's SSH proxy: an interactive bash on a PTY that, like
# the proxy, ignores any command on its argv, echoes what is typed and ends
# the session when the shell exits. `script` differs between BSD and util-linux.
_SHELL = "bash --norc --noprofile -i"
_FAKE_PROXY = (
    ["script", "-q", "/dev/null", *_SHELL.split()] if sys.platform == "darwin"
    else ["script", "-qfec", _SHELL, "/dev/null"]
)


@unittest.skipUnless(shutil.which("bash") and shutil.which("script"),
                     "needs bash and script")
class CommandsOverAnInteractiveProxy(unittest.TestCase):
    """The proxy hands out a shell and ignores `ssh host <cmd>`: sending the
    command as an argument made every probe hang until its timeout."""

    EP = SshEndpoint(PROXY_HOST, 22, "tok", pty=True)

    def _run(self, fn, *args):
        with mock.patch.object(checks, "_ssh_command_prefix",
                               side_effect=lambda _e: list(_FAKE_PROXY)):
            return fn(self.EP, *args)

    def test_probe_succeeds(self):
        self.assertEqual(self._run(checks.ssh_probe, 15), (True, ""))

    def test_exit_status_and_output_survive_the_shell(self):
        cmd = "echo \"it's\"; cat <<EOF\nx $((2+2))\nEOF\nexit 3"
        r = self._run(checks.run_ssh, cmd, 15)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "it's\nx 4\n")

    def test_simple_check_failure_is_reported(self):
        self.assertEqual(
            self._run(checks.run_simple_check, "echo FAIL: nope; false", 15),
            (False, "FAIL: nope"),
        )

    def test_typed_echo_is_not_mistaken_for_the_result(self):
        rc, out = checks._pty_result(
            'echo "__SMOKE_""BEGIN__"; bash -c "$(echo eA== | base64 -d)"; '
            'echo "__SMOKE_""RC=$?__"; exit\r\n'
            "prompt$ \r\n"
        )
        self.assertIsNone(rc)   # never ran: a dropped session, not a pass


class NonPtyEndpointsNeverTouchTheTerminal(unittest.TestCase):
    def test_stdin_is_devnull(self):
        with mock.patch.object(checks.subprocess, "run") as run:
            run.return_value = checks.subprocess.CompletedProcess([], 0, "ready\n", "")
            checks.ssh_probe(SshEndpoint("1.2.3.4", 40022))
        self.assertIs(run.call_args.kwargs["stdin"], checks.subprocess.DEVNULL)
