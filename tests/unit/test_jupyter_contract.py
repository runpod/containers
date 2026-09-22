"""Every template's start.sh must treat the JupyterLab token the same way.

Two independent scripts launch Jupyter: container-template/start.sh (copied
into official-templates/base, so pytorch, rocm, autoresearch and
pytorch-cluster inherit it) and official-templates/comfyui's own copy. They
have already drifted once in each direction -- ComfyUI served an
unauthenticated JupyterLab when JUPYTER_PASSWORD was unset, then replaced that
with a token generated per boot that the console can never read.

Each test below states one rule and asserts it against every script, by
running the real start_jupyter with a fake `jupyter` on PATH and inspecting
the arguments it was invoked with. Adding a template means adding its
start.sh to SCRIPTS; the rules then apply to it too.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCRIPTS = [
    "container-template/start.sh",
    "official-templates/comfyui/scripts/start.sh",
]

# Absolute paths the scripts write to as root. Rewritten into the sandbox so
# the test runs as an ordinary user; nothing else about the function changes.
SANDBOXED_PATHS = ["/jupyter.log", "/workspace"]

NOT_STARTED = object()

# A fake `jupyter` and a fake `python -m jupyter` — the two scripts invoke it
# differently — recording argv and exiting at once, so the `wait` below is
# immediate. One script then reports "FAILED to start" because the child is
# already gone; that is irrelevant here, the recorded argv is what matters.
STUB = """#!/bin/bash
printf '%s\\n' "$*" >> "$RECORD"
"""


def extract_start_jupyter(script: Path) -> str:
    body = re.search(
        r"^start_jupyter\(\) \{.*?^\}", script.read_text(), re.S | re.M
    )
    if not body:
        raise AssertionError(
            f"{script}: no start_jupyter() function found. If it was renamed, "
            "update this test — the Jupyter token rules still have to hold."
        )
    return body.group(0)


def run_start_jupyter(script_rel: str, env: dict, sandbox: Path) -> object:
    """Run the real start_jupyter under `env`; return the token, or NOT_STARTED."""
    work = Path(tempfile.mkdtemp(dir=sandbox))
    record = work / "argv"
    bindir = work / "bin"
    bindir.mkdir()
    for name in ("jupyter", "python"):
        stub = bindir / name
        stub.write_text(STUB)
        stub.chmod(0o755)

    func = extract_start_jupyter(REPO_ROOT / script_rel)
    for path in SANDBOXED_PATHS:
        func = func.replace(path, str(work) + path)

    child_env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "RECORD": str(record),
        "HOME": str(work),
        **env,
    }
    subprocess.run(
        # Jupyter is backgrounded; `wait` makes the recording deterministic
        # instead of racing the parent shell's exit.
        ["bash", "-c", f"{func}\nstart_jupyter\nwait"],
        env=child_env,
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if not record.exists() or not record.read_text().strip():
        return NOT_STARTED
    argv = record.read_text()
    token = re.search(r"--IdentityProvider\.token=(\S*)", argv)
    if not token:
        raise AssertionError(
            f"{script_rel}: jupyter was started without an "
            f"--IdentityProvider.token argument at all: {argv!r}"
        )
    return token.group(1)


class JupyterTokenContract(unittest.TestCase):
    """The same rules, asserted against every template start script."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.sandbox = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def token_for(self, script: str, env: dict) -> object:
        return run_start_jupyter(script, env, self.sandbox)

    def test_no_password_does_not_start_jupyter(self) -> None:
        """Rule 1. The regression TEM-89 introduced: with nothing set, the
        container must not invent a token — a container-side token never
        reaches the pod env, so the console cannot use it and it changes
        every boot."""
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertIs(
                    self.token_for(script, {}),
                    NOT_STARTED,
                    "no JUPYTER_PASSWORD must mean no JupyterLab",
                )

    def test_password_becomes_the_token(self) -> None:
        """Rule 2. The console builds the Connect URL from the pod env's
        JUPYTER_PASSWORD, so the token has to be that value verbatim."""
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(
                    self.token_for(script, {"JUPYTER_PASSWORD": "s3cret-token"}),
                    "s3cret-token",
                )

    def test_disable_auth_starts_with_empty_token(self) -> None:
        """Rule 3. The documented opt-out, and the only way to get an empty
        token on purpose."""
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(
                    self.token_for(script, {"JUPYTER_DISABLE_AUTH": "true"}),
                    "",
                )

    def test_disable_auth_requires_the_exact_string_true(self) -> None:
        """Rule 4. Truthy-ish values must not open a pod: an unauthenticated
        JupyterLab on the public proxy is a root shell for anyone with the URL,
        which is the hole TEM-89 closed."""
        for script in SCRIPTS:
            for value in ("1", "yes", "TRUE", "True", ""):
                with self.subTest(script=script, value=value):
                    self.assertIs(
                        self.token_for(script, {"JUPYTER_DISABLE_AUTH": value}),
                        NOT_STARTED,
                        f"JUPYTER_DISABLE_AUTH={value!r} must not disable auth",
                    )

    def test_disable_auth_takes_precedence_over_password(self) -> None:
        """Rule 5. Both set is documented as auth-off in the READMEs; the
        scripts must agree with the docs."""
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(
                    self.token_for(
                        script,
                        {
                            "JUPYTER_PASSWORD": "s3cret-token",
                            "JUPYTER_DISABLE_AUTH": "true",
                        },
                    ),
                    "",
                )


if __name__ == "__main__":
    unittest.main()
