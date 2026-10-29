"""Unit tests for the opt-in image hygiene checks.

The commands themselves only run inside a pod, so what is testable here is
everything around them: that a group gets exactly the checks it opted into,
that manifest-supplied names reach the command without breaking out of their
quoting, and that the pip-check allow-list gates pass/fail the way the
manifest promises.
"""

import shutil
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
        labels = [label for label, _, _ in _hygiene_checks("grp")]
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
        labels = [label for label, _, _ in _hygiene_checks("grp")]
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
        (_, command, _), = _hygiene_checks("grp")
        for name in checks.REVOKED_CA_NAMES:
            self.assertIn(name, command)

    def test_group_override_replaces_the_default(self):
        config.GROUP_TEST_CA_CERTS["grp"] = True
        config.GROUP_REVOKED_CA_NAMES["grp"] = ["SomeOtherRoot"]
        (_, command, _), = _hygiene_checks("grp")
        self.assertIn("SomeOtherRoot", command)
        self.assertNotIn("emSign", command)

    def test_override_reaches_the_certifi_check_too(self):
        config.GROUP_TEST_PYTHON_TLS["grp"] = True
        config.GROUP_REVOKED_CA_NAMES["grp"] = ["SomeOtherRoot"]
        (_, command, _), = _hygiene_checks("grp")
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

    def test_names_identify_one_root_not_a_family(self):
        # Distrust is per root: Ubuntu ships emSign ECC Root CA - G3
        # disabled while still trusting C1, C3 and G1. A family prefix
        # would fail on three roots nobody revoked.
        for name in checks.REVOKED_CA_NAMES:
            with self.subTest(name=name):
                self.assertGreater(
                    len(name.split()), 1,
                    f"{name!r} names a family, not a root",
                )

    def test_matching_normalises_underscores_to_spaces(self):
        # One spelling has to match both haystacks: openssl prints
        # 'CN=emSign Root CA - G1', the filename fallback has
        # 'emSign_Root_CA_-_G1.pem'.
        command = checks.ca_certs_check_command(("emSign Root CA - G1",))
        self.assertEqual(command.count("tr '_' ' '"), 2)

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
            "autoresearch": checks.autoresearch_check_command(),
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

    def test_autoresearch_runs_train_in_the_venv(self):
        command = checks.autoresearch_check_command()
        self.assertIn("/opt/autoresearch/.venv/bin/activate", command)
        self.assertIn("runpy.run_path('train.py'", command)
        self.assertIn("prepare.TIME_BUDGET = 5", command)
        # Sequence length is shrunk so the check fits a cheap GPU.
        self.assertIn("prepare.MAX_SEQ_LEN = 256", command)

    def test_ca_check_proves_tls_still_works(self):
        # Over-pruning a trust store is as broken as not pruning it, so a
        # clean name scan alone must not be enough to pass.
        self.assertIn("https://pypi.org/simple/", checks.ca_certs_check_command())


class SetEFragmentTests(unittest.TestCase):
    """The fragments that `set -e` is easy to get wrong in.

    Every hygiene command runs under `set -e`, where a plain `cmd && echo`
    or a loop ending on a false test changes the exit status of the whole
    check. Both shapes shipped once and had to be fixed: the uv scan killed
    the check before it reported anything, and the TLS probe would have let
    a broken trust store pass.
    """

    def _bin(self, name: str, body: str) -> str:
        d = Path(tempfile.mkdtemp())
        script = d / name
        script.write_text(f"#!/bin/bash\n{body}\n")
        script.chmod(0o755)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return str(d)

    def _run(self, fragment: str, *dirs: str):
        # Fake binaries win, then the real PATH so tr/sed/wc resolve.
        path = ":".join([*dirs, "/usr/bin", "/bin"])
        return subprocess.run(
            ["/bin/bash", "-c", f"set -e; {fragment}; echo REACHED_END"],
            capture_output=True, text=True, env={"PATH": path},
        )

    def _empty_dir(self) -> str:
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_uv_scan_survives_a_path_entry_without_uv(self):
        # The regression: a $PATH entry with no uv made the last loop
        # iteration exit 1, which killed the command substitution and —
        # under set -e — the whole check, before it reported anything.
        with_uv = self._bin("uv", "echo uv 0.0.0")
        proc = self._run(
            checks._UV_PATH_SCAN + '; printf "%s\\n" "$FOUND"',
            with_uv, self._empty_dir(),
        )
        self.assertIn("REACHED_END", proc.stdout, proc.stderr)
        self.assertIn(f"{with_uv}/uv", proc.stdout)

    def test_uv_scan_finds_every_copy(self):
        first = self._bin("uv", "true")
        second = self._bin("uv", "true")
        proc = self._run(
            checks._UV_PATH_SCAN + '; printf "%s\\n" "$FOUND"',
            first, second,
        )
        self.assertIn("REACHED_END", proc.stdout, proc.stderr)
        self.assertIn(f"{first}/uv", proc.stdout)
        self.assertIn(f"{second}/uv", proc.stdout)

    def test_uv_scan_dedupes_a_symlinked_path_entry(self):
        # usr-merge: /bin is a symlink to /usr/bin, so one uv is reachable
        # under two PATH entries. The scan must collapse them to a single copy.
        real = self._bin("uv", "true")
        parent = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, parent, ignore_errors=True)
        link = Path(parent) / "bin"
        link.symlink_to(real)
        proc = self._run(
            checks._UV_PATH_SCAN + '; printf "%s\\n" "$FOUND"',
            real, str(link),
        )
        self.assertIn("REACHED_END", proc.stdout, proc.stderr)
        hits = [ln for ln in proc.stdout.splitlines() if ln.endswith("/uv")]
        self.assertEqual(len(hits), 1, proc.stdout)

    def test_uv_scan_survives_when_no_entry_has_uv(self):
        proc = self._run(
            checks._UV_PATH_SCAN + '; printf "%s\\n" "$FOUND"',
            self._empty_dir(), self._empty_dir(),
        )
        self.assertIn("REACHED_END", proc.stdout, proc.stderr)

    def test_tls_probe_fails_the_check_when_the_fetch_fails(self):
        # A broken trust store must not reach a passing exit status.
        failing_curl = self._bin("curl", "exit 60")
        proc = self._run(checks._TLS_PROBE, failing_curl)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("REACHED_END", proc.stdout)

    def test_tls_probe_passes_when_the_fetch_succeeds(self):
        ok_curl = self._bin("curl", "exit 0")
        proc = self._run(checks._TLS_PROBE, ok_curl)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("REACHED_END", proc.stdout)


class CaCertsVersionFloorTests(unittest.TestCase):
    """The floor is the direct check: the distrust decision is the distro's,
    so what we assert is that its patched package actually arrived."""

    FLOOR = "20260816"
    # The patched builds the base Dockerfile pins, plus the pre-fix ones.
    PATCHED = ("20260816ubuntu0.24.04.1", "20260816ubuntu0.26.04.1")
    STALE = ("20240203", "20250419ubuntu0.24.04.1")

    def _compare(self, installed: str) -> int:
        """dpkg's own comparison, which is what the check shells out to."""
        return subprocess.run(
            ["dpkg", "--compare-versions", installed, "ge", self.FLOOR],
        ).returncode

    @unittest.skipIf(shutil.which("dpkg") is None, "dpkg not available")
    def test_patched_versions_clear_the_floor(self):
        for version in self.PATCHED:
            with self.subTest(version=version):
                self.assertEqual(self._compare(version), 0)

    @unittest.skipIf(shutil.which("dpkg") is None, "dpkg not available")
    def test_pre_fix_versions_do_not(self):
        for version in self.STALE:
            with self.subTest(version=version):
                self.assertNotEqual(self._compare(version), 0)

    def test_floor_is_only_emitted_when_asked_for(self):
        self.assertNotIn(
            "compare-versions", checks.ca_certs_check_command(("x",)),
        )
        self.assertIn(
            "compare-versions",
            checks.ca_certs_check_command(("x",), self.FLOOR),
        )

    def test_a_missing_package_fails_rather_than_passing_the_floor(self):
        # dpkg-query on an absent package yields an empty version, which
        # must not quietly compare as "good enough".
        command = checks.ca_certs_check_command(("x",), self.FLOOR)
        self.assertIn("ca-certificates is not installed via dpkg", command)

    def test_floor_is_quoted(self):
        command = checks.ca_certs_check_command(("x",), "2026; rm -rf /")
        proc = subprocess.run(
            ["bash", "-n"], input=command, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("'2026; rm -rf /'", command)


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
