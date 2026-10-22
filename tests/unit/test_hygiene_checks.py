"""Unit tests for the opt-in image hygiene checks.

The commands themselves only run inside a pod, so what is testable here is
everything around them: that a group gets exactly the checks it opted into,
that manifest-supplied names reach the command without breaking out of their
quoting, and that the pip-check allow-list gates pass/fail the way the
manifest promises.
"""

import subprocess
import tempfile
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runpod_smoke import checks, config  # noqa: E402
from runpod_smoke.runner import _hygiene_checks  # noqa: E402


def _reset_groups() -> None:
    for d in (
        config.GROUP_TEST_PIP_CHECK,
        config.GROUP_PIP_CHECK_ALLOW,
        config.GROUP_TEST_CA_CERTS,
        config.GROUP_TEST_PYTHON_TLS,
        config.GROUP_REVOKED_CA_NAMES,
        config.GROUP_PYTHON_TLS_VENV,
        config.GROUP_TEST_UV,
        config.GROUP_TEST_VIRTUALENV,
    ):
        d.clear()


def _run_pip_program(allowed, pip_output: str, pip_rc: int):
    """Execute the embedded pip-check program with `pip check` stubbed out.

    Returns (exit_code, printed_lines). exit_code is 0 when the program ran
    to completion without calling sys.exit.
    """
    command = checks.pip_check_command(allowed)
    program = command.split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0]

    fake = types.ModuleType("subprocess")
    fake.run = lambda *a, **k: types.SimpleNamespace(
        stdout=pip_output, stderr="", returncode=pip_rc,
    )
    printed: list[str] = []
    saved = sys.modules.get("subprocess")
    sys.modules["subprocess"] = fake
    try:
        exec(program, {"print": printed.append, "__name__": "__main__"})
        code = 0
    except SystemExit as exc:
        code = exc.code or 0
    finally:
        if saved is not None:
            sys.modules["subprocess"] = saved
    return code, printed


class HygieneSelectionTests(unittest.TestCase):
    """Only the opted-in checks run, and always in the same order."""

    def setUp(self):
        _reset_groups()
        self.addCleanup(_reset_groups)

    def test_no_flags_means_no_checks(self):
        self.assertEqual(_hygiene_checks("grp"), [])

    def test_only_opted_in_checks_appear(self):
        config.GROUP_TEST_UV["grp"] = True
        labels = [label for label, _ in _hygiene_checks("grp")]
        self.assertEqual(labels, ["uv"])

    def test_order_is_cheap_checks_first(self):
        for d in (
            config.GROUP_TEST_PIP_CHECK,
            config.GROUP_TEST_CA_CERTS,
            config.GROUP_TEST_PYTHON_TLS,
            config.GROUP_TEST_UV,
            config.GROUP_TEST_VIRTUALENV,
        ):
            d["grp"] = True
        labels = [label for label, _ in _hygiene_checks("grp")]
        self.assertEqual(
            labels,
            [
                "pip check",
                "virtualenv",
                "uv",
                "CA trust store",
                "certifi / python TLS",
            ],
        )

    def test_flags_are_per_group(self):
        config.GROUP_TEST_CA_CERTS["one"] = True
        self.assertEqual([lbl for lbl, _ in _hygiene_checks("two")], [])


class RevokedCaNameTests(unittest.TestCase):
    """Manifest-supplied CA names reach both stores, and stay inert."""

    def setUp(self):
        _reset_groups()
        self.addCleanup(_reset_groups)

    def test_default_list_is_used_when_group_sets_none(self):
        config.GROUP_TEST_CA_CERTS["grp"] = True
        (_, command), = _hygiene_checks("grp")
        for name in checks.REVOKED_CA_NAMES:
            self.assertIn(name, command)

    def test_group_override_replaces_the_default(self):
        config.GROUP_TEST_CA_CERTS["grp"] = True
        config.GROUP_REVOKED_CA_NAMES["grp"] = ["SomeOtherRoot"]
        (_, command), = _hygiene_checks("grp")
        self.assertIn("SomeOtherRoot", command)
        self.assertNotIn("emSign", command)

    def test_override_reaches_the_certifi_check_too(self):
        config.GROUP_TEST_PYTHON_TLS["grp"] = True
        config.GROUP_REVOKED_CA_NAMES["grp"] = ["SomeOtherRoot"]
        (_, command), = _hygiene_checks("grp")
        self.assertIn("SomeOtherRoot", command)

    def test_shell_metacharacters_in_a_name_stay_literal(self):
        # The names come from a manifest, which CI generates from a workflow
        # input. A name must reach grep as one word, never run as a command.
        marker = Path(tempfile.gettempdir()) / "hygiene-quoting-probe"
        marker.unlink(missing_ok=True)
        names = [f"x'; touch {marker}; '", "plain Root"]
        loop = (
            f"for n in {checks._sh_quote_list(names)}; "
            "do printf '%s\\n' \"$n\"; done"
        )
        proc = subprocess.run(
            ["bash", "-c", loop], capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), names)
        self.assertFalse(marker.exists(), "quoted name was executed")

    def test_a_quoted_name_does_not_break_the_command(self):
        command = checks.ca_certs_check_command(["x'; touch /tmp/pwned; '"])
        proc = subprocess.run(
            ["bash", "-n"], input=command, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class CommandShapeTests(unittest.TestCase):
    """Each generated command is valid shell and says what it must."""

    def test_every_command_is_syntactically_valid_shell(self):
        commands = {
            "pip_check": checks.pip_check_command(("a b", "c'd")),
            "ca_certs": checks.ca_certs_check_command(("emSign",)),
            "python_tls": checks.python_tls_check_command(
                ("emSign",), "/opt/a b/activate",
            ),
            "uv": checks.uv_check_command(),
            "virtualenv": checks.virtualenv_check_command(),
        }
        for name, command in commands.items():
            with self.subTest(command=name):
                proc = subprocess.run(
                    ["bash", "-n"], input=command,
                    capture_output=True, text=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_python_tls_sources_the_venv_when_given(self):
        plain = checks.python_tls_check_command(("emSign",))
        self.assertFalse(plain.startswith(". "))
        venv = checks.python_tls_check_command(
            ("emSign",), "/opt/a b/activate",
        )
        self.assertTrue(venv.startswith(". '/opt/a b/activate'; "))

    def test_uv_check_rejects_a_second_copy_on_path(self):
        command = checks.uv_check_command()
        self.assertIn("expected one uv on PATH", command)
        self.assertIn("uv is also installed as a pip package", command)

    def test_ca_check_proves_tls_still_works(self):
        # Over-pruning a trust store is as broken as not pruning it, so a
        # clean name scan alone must not be enough to pass.
        self.assertIn("https://pypi.org/simple/", checks.ca_certs_check_command())


class PipCheckGatingTests(unittest.TestCase):
    """The allow-list decides pass/fail, and only for what it names."""

    CONFLICTS = (
        "datasets 4.4.1 has requirement fsspec<=2025.10.0, "
        "but you have fsspec 2026.6.0\n"
        "nvidia-resiliency-ext 0.4.1 requires pynvml, which is not installed."
    )

    def test_clean_pip_check_passes(self):
        code, printed = _run_pip_program((), "No broken requirements found.", 0)
        self.assertEqual(code, 0)
        self.assertTrue(any("pip check ok" in line for line in printed))

    def test_unlisted_conflict_fails(self):
        code, printed = _run_pip_program((), self.CONFLICTS, 1)
        self.assertEqual(code, 1)
        self.assertTrue(any("FAIL" in line for line in printed))

    def test_fully_allowed_conflicts_pass(self):
        code, _ = _run_pip_program(
            ("datasets 4.4.1", "nvidia-resiliency-ext"), self.CONFLICTS, 1,
        )
        self.assertEqual(code, 0)

    def test_a_new_conflict_still_fails_when_others_are_allowed(self):
        # The point of the allow-list: it must not become a blanket mute.
        code, printed = _run_pip_program(
            ("datasets 4.4.1",), self.CONFLICTS, 1,
        )
        self.assertEqual(code, 1)
        self.assertTrue(
            any("nvidia-resiliency-ext" in line for line in printed)
        )

    def test_allow_entries_are_matched_as_plain_substrings(self):
        # They are substrings, not patterns — a regex-looking entry must not
        # quietly match everything.
        code, _ = _run_pip_program((".*",), self.CONFLICTS, 1)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
