"""The ComfyUI start.sh rules for ComfyUI's password, FileBrowser's password,
ComfyUI-Manager's security settings and user-supplied ComfyUI arguments.

Like test_jupyter_contract, each test runs the real shell function pulled out
of official-templates/comfyui/scripts/start.sh, with fakes on PATH where it
calls out, and checks what it did. The rules are the Jupyter ones: a password
variable means it is enforced, an explicit *_DISABLE_AUTH=true runs without
one, and neither means the service does not start. No password ever reaches
the output, which is the pod log.
"""

import argparse
import configparser
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "official-templates/comfyui/scripts/start.sh"
SECRET = "pod-secret-value-1234"


def function(name: str) -> str:
    body = re.search(rf"^{name}\(\) \{{.*?^\}}", SCRIPT.read_text(), re.S | re.M)
    if not body:
        raise AssertionError(
            f"{SCRIPT}: no {name}() function found. If it was renamed, update "
            "this test; the rule it carries still has to hold."
        )
    return body.group(0)


def constants(*names: str) -> str:
    """The script's top-level NAME=value lines, for functions that read them."""
    lines = []
    for name in names:
        line = re.search(rf"^{name}=.*$", SCRIPT.read_text(), re.M)
        if not line:
            raise AssertionError(f"{SCRIPT}: no {name}= assignment found.")
        lines.append(line.group(0))
    return "\n".join(lines) + "\n"


class Sandbox(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()

    def run_bash(self, script: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", script],
            env={"PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.work), **env},
            cwd=self.work, capture_output=True, text=True, timeout=60,
        )


class ComfyUIAuthMode(Sandbox):
    def mode(self, env: dict) -> tuple[str, str]:
        result = self.run_bash(
            constants("COMFYUI_PASSWORD_MIN_LENGTH")
            + function("resolve_comfyui_auth")
            + '\nresolve_comfyui_auth\necho "MODE=$COMFYUI_AUTH_MODE"'
            + '\necho "REASON=$COMFYUI_OFF_REASON"', env)
        mode = re.search(r"^MODE=(\w*)$", result.stdout, re.M).group(1)
        return mode, result.stdout + result.stderr

    def test_short_password_does_not_start_comfyui(self) -> None:
        for password in ("a", "x" * 11):
            with self.subTest(length=len(password)):
                mode, out = self.mode({"COMFYUI_PASSWORD": password})
                self.assertEqual(mode, "off")
                self.assertIn("REASON=is shorter than 12 characters", out)
        self.assertEqual(self.mode({"COMFYUI_PASSWORD": "x" * 12})[0], "proxy")
        _, out = self.mode({})
        self.assertIn("REASON=is not set", out)

    def test_password_puts_the_proxy_in_front(self) -> None:
        mode, out = self.mode({"COMFYUI_PASSWORD": SECRET})
        self.assertEqual(mode, "proxy")
        self.assertNotIn(SECRET, out)

    def test_neither_variable_does_not_start_comfyui(self) -> None:
        self.assertEqual(self.mode({})[0], "off")
        self.assertEqual(self.mode({"COMFYUI_PASSWORD": ""})[0], "off")

    def test_disable_auth_is_the_only_way_to_run_without(self) -> None:
        mode, out = self.mode({"COMFYUI_DISABLE_AUTH": "true"})
        self.assertEqual(mode, "disabled")
        self.assertIn("NO authentication", out)
        for value in ("1", "yes", "TRUE", "True", " true"):
            with self.subTest(value=value):
                self.assertEqual(self.mode({"COMFYUI_DISABLE_AUTH": value})[0], "off")

    def test_disable_auth_wins_like_jupyter(self) -> None:
        mode, out = self.mode({"COMFYUI_DISABLE_AUTH": "true", "COMFYUI_PASSWORD": SECRET})
        self.assertEqual(mode, "disabled")
        self.assertNotIn(SECRET, out)


class MainProgram(unittest.TestCase):
    """The parts of the main program that are not functions, read as text."""

    text = SCRIPT.read_text()

    def test_off_holds_the_pod_before_comfyui_setup(self) -> None:
        gate = re.search(
            r'^if \[ "\$COMFYUI_AUTH_MODE" = off \]; then\n(.*?)^fi$',
            self.text, re.S | re.M)
        self.assertIsNotNone(gate, "the COMFYUI_AUTH_MODE=off gate is gone")
        self.assertIn("COMFYUI_PASSWORD $COMFYUI_OFF_REASON", gate.group(1))
        self.assertIn("hold_pod", gate.group(1))
        self.assertIn("exit 0", gate.group(1))
        self.assertLess(gate.start(), self.text.index("\nupgrade_comfyui_if_needed\n"))
        self.assertLess(gate.start(), self.text.index("python main.py"))
        self.assertGreater(gate.start(), self.text.index("trap on_shutdown SIGTERM SIGINT"),
                           "a stop during the hold must still run on_shutdown")

    def test_shutdown_stops_the_restart_loop_then_the_proxy(self) -> None:
        shutdown = function("on_shutdown")
        loop = shutdown.index('kill "$PROXY_PID"')
        self.assertLess(loop, shutdown.index('pkill -TERM -f "$AUTH_PROXY"'))

    def test_no_permissive_cors(self) -> None:
        launch = self.text[self.text.index("COMFY_ARGS=("):]
        self.assertNotIn("--enable-cors-header", launch.split("python main.py")[0]
                         .replace("# No --enable-cors-header", ""))

    def test_passwords_are_never_echoed(self) -> None:
        for line in self.text.splitlines():
            if re.search(r"\b(echo|printf)\b", line):
                with self.subTest(line=line.strip()):
                    self.assertNotRegex(
                        line, r"\$\{?(COMFYUI|FILEBROWSER)_PASSWORD(?!\w)")


class UserArgs(Sandbox):
    def args(self, content: str) -> tuple[list, str]:
        args_file = self.work / "comfyui_args.txt"
        args_file.write_text(content)
        result = self.run_bash(
            function("append_user_args")
            + "\nCOMFY_ARGS=(--listen 127.0.0.1 --port 18188)"
            + "\nappend_user_args\nprintf 'ARG:%s\\n' \"${COMFY_ARGS[@]}\"",
            {"ARGS_FILE": str(args_file)})
        args = re.findall(r"^ARG:(.*)$", result.stdout, re.M)
        return args, result.stdout

    def test_listen_and_port_cannot_be_overridden(self) -> None:
        cases = {
            "--listen 0.0.0.0\n--preview-method auto\n": ["--preview-method", "auto"],
            "--listen\n--lowvram\n": ["--lowvram"],
            "--listen --port 9000 --lowvram": ["--lowvram"],
            "--listen=0.0.0.0 --port=8188\n--lowvram": ["--lowvram"],
            "# --listen 0.0.0.0\n--max-batch-size 8": ["--max-batch-size", "8"],
            "--port 8188 --listen 0.0.0.0,::": [],
        }
        for content, extra in cases.items():
            with self.subTest(content=content):
                args, out = self.args(content)
                self.assertEqual(args, ["--listen", "127.0.0.1", "--port", "18188", *extra])
                if "--listen" in content.replace("# --listen", ""):
                    self.assertIn("WARNING: ignoring --listen", out)

    def test_other_arguments_pass_through(self) -> None:
        args, _ = self.args("--max-batch-size 8\n--preview-method auto\n")
        self.assertEqual(args[4:], ["--max-batch-size", "8", "--preview-method", "auto"])

    def test_double_dash_is_dropped(self) -> None:
        args, out = self.args("--lowvram\n--\n")
        self.assertEqual(args[4:], ["--lowvram"])
        self.assertIn("WARNING: ignoring --", out)


class ComfyArgs(Sandbox):
    """build_comfy_args: what ComfyUI ends up listening on, as its own
    argparse would read the final command line."""

    def build(self, mode: str, content: str) -> tuple[list, str]:
        args_file = self.work / "comfyui_args.txt"
        args_file.write_text(content)
        result = self.run_bash(
            constants("COMFYUI_PUBLIC_PORT", "COMFYUI_INTERNAL_PORT")
            + function("append_user_args") + "\n" + function("build_comfy_args")
            + "\nbuild_comfy_args\nprintf 'ARG:%s\\n' \"${COMFY_ARGS[@]}\""
            + '\necho "PORT=$COMFY_LISTEN_PORT"',
            {"ARGS_FILE": str(args_file), "COMFYUI_AUTH_MODE": mode})
        args = re.findall(r"^ARG:(.*)$", result.stdout, re.M)
        port = re.search(r"^PORT=(\d+)$", result.stdout, re.M).group(1)
        return args, port

    @staticmethod
    def parse(args: list):
        """The --listen/--port definitions from ComfyUI's comfy/cli_args.py,
        with argparse's defaults (prefix matching on, last value wins)."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--listen", type=str, default="127.0.0.1",
                            nargs="?", const="0.0.0.0,::")
        parser.add_argument("--port", type=int, default=8188)
        parser.add_argument("--lowvram", action="store_true")
        parser.add_argument("--log-stdout", action="store_true")
        return parser.parse_args(args)

    def test_comfyui_is_loopback_only_behind_the_proxy(self) -> None:
        args, port = self.build("proxy", "")
        self.assertEqual(port, "18188")
        parsed = self.parse(args)
        self.assertEqual((parsed.listen, parsed.port), ("127.0.0.1", 18188))

    def test_disabled_listens_on_the_public_port(self) -> None:
        args, port = self.build("disabled", "")
        self.assertEqual(port, "8188")
        parsed = self.parse(args)
        self.assertEqual((parsed.listen, parsed.port), ("0.0.0.0", 8188))

    def test_abbreviated_flags_cannot_open_comfyui(self) -> None:
        """argparse takes `--lis` for --listen; the script's own flags come
        last, so they win whatever the args file says."""
        for content in ("--lis 0.0.0.0 --po 8188", "--liste\n--lowvram",
                        "--listen 0.0.0.0", "--lis=0.0.0.0 --por=1"):
            with self.subTest(content=content):
                args, _ = self.build("proxy", content)
                parsed = self.parse(args)
                self.assertEqual((parsed.listen, parsed.port), ("127.0.0.1", 18188))


class AuthProxyRestart(Sandbox):
    def test_proxy_is_restarted_until_it_refuses_its_config(self) -> None:
        runs = self.work / "runs"
        fake = self.bin / "fake-python"
        # Exits 1 (a crash) twice, then 2 (bad config).
        fake.write_text(
            "#!/bin/bash\n"
            f'echo "$COMFYUI_PROXY_PORT $COMFYUI_UPSTREAM" >> {runs}\n'
            f'[ "$(wc -l < {runs})" -ge 3 ] && exit 2\n'
            "exit 1\n")
        fake.chmod(0o755)
        result = self.run_bash(
            constants("COMFYUI_PUBLIC_PORT", "COMFYUI_INTERNAL_PORT")
            + function("run_auth_proxy") + "\nrun_auth_proxy",
            {"SYSTEM_PYTHON": str(fake), "AUTH_PROXY": "proxy.py",
             "AUTH_PROXY_RESTART_DELAY": "0", "COMFYUI_PASSWORD": SECRET})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(runs.read_text().splitlines(),
                         ["8188 127.0.0.1:18188"] * 3)
        self.assertEqual(result.stdout.count("restarting it"), 2)
        self.assertIn("refused to start", result.stdout)
        self.assertNotIn(SECRET, result.stdout + result.stderr)


class ManagerSecurity(Sandbox):
    def pin(self) -> subprocess.CompletedProcess:
        return self.run_bash(
            function("pin_manager_security") + "\npin_manager_security",
            {"SYSTEM_PYTHON": sys.executable, "COMFYUI_DIR": str(self.work / "ComfyUI")})

    def read(self, path: Path) -> configparser.SectionProxy:
        config = configparser.ConfigParser(interpolation=None)
        config.read(path)
        return config["default"]

    def assert_pinned(self, path: Path) -> None:
        section = self.read(path)
        self.assertEqual(section["security_level"], "normal")
        self.assertEqual(section["allow_git_url_install"], "False")
        self.assertEqual(section["allow_pip_install"], "False")

    def test_fresh_volume_gets_a_pinned_config(self) -> None:
        self.pin()
        self.assert_pinned(self.work / "ComfyUI/user/__manager/config.ini")

    def test_weakened_config_is_pinned_and_the_rest_kept(self) -> None:
        path = self.work / "ComfyUI/user/__manager/config.ini"
        path.parent.mkdir(parents=True)
        path.write_text(
            "[default]\nsecurity_level = weak\nallow_git_url_install = True\n"
            "allow_pip_install = true\nchannel_url = https://example.invalid/%x\n"
            "preview_method = auto\n")
        self.pin()
        self.assert_pinned(path)
        self.assertEqual(self.read(path)["preview_method"], "auto")
        self.assertEqual(self.read(path)["channel_url"], "https://example.invalid/%x")

    def test_legacy_config_awaiting_migration_is_pinned_in_place(self) -> None:
        """Manager moves a legacy config into __manager only while the new one
        is absent, so the legacy file is pinned and the new one not created."""
        legacy = self.work / "ComfyUI/user/default/ComfyUI-Manager/config.ini"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("[default]\nsecurity_level = normal-\n")
        self.pin()
        self.assert_pinned(legacy)
        self.assertFalse((self.work / "ComfyUI/user/__manager/config.ini").exists())


FAKE_FILEBROWSER = """#!/bin/bash
printf '%s\\n' "$*" >> "$RECORD"
case "$*" in
  *"users find admin"*) [ -n "$FB_HAS_ADMIN" ] || { echo "user not found"; exit 1; } ;;
esac
if [ -n "$FB_FAIL" ] && [[ "$*" == *"$FB_FAIL"* ]]; then
  echo "Error: refused: $*"
  exit 1
fi
"""


class FileBrowser(Sandbox):
    def start(self, env: dict, db_exists: bool = False, **fake) -> tuple[list, str]:
        fake_bin = self.bin / "filebrowser"
        fake_bin.write_text(FAKE_FILEBROWSER)
        fake_bin.chmod(0o755)
        record = self.work / "argv"
        db = self.work / "filebrowser.db"
        if db_exists:
            db.write_text("")
        funcs = (function("filebrowser_cli") + "\n" + function("start_filebrowser")
                 ).replace("/filebrowser.log", str(self.work / "filebrowser.log"))
        result = self.run_bash(
            funcs + "\nstart_filebrowser\nwait",
            {"RECORD": str(record), "DB_FILE": str(db), **fake, **env})
        calls = record.read_text().splitlines() if record.exists() else []
        return calls, result.stdout + result.stderr

    @staticmethod
    def served(calls: list) -> bool:
        return any(re.fullmatch(r"-d \S+", c) for c in calls)

    def test_no_password_does_not_start_filebrowser(self) -> None:
        calls, out = self.start({}, db_exists=True)
        self.assertEqual(calls, [], "not even the CLI may run")
        self.assertIn("FILEBROWSER_PASSWORD is not set, so FileBrowser was not started.", out)
        # Boxed like the ComfyUI banner, so it is not lost above ComfyUI's
        # startup output.
        box = out.split("=============================================")
        self.assertEqual(len(box), 3, out)
        self.assertIn("FileBrowser was not started", box[1])

    def test_no_default_password_anywhere(self) -> None:
        self.assertNotIn("adminadmin12", function("start_filebrowser"))

    def test_password_on_a_new_volume(self) -> None:
        calls, out = self.start({"FILEBROWSER_PASSWORD": SECRET})
        self.assertTrue(any("config init" in c for c in calls))
        self.assertTrue(any("--auth.method=json" in c for c in calls))
        self.assertTrue(any(f"users add admin {SECRET} --perm.admin" in c for c in calls))
        self.assertTrue(self.served(calls))
        self.assertNotIn(SECRET, out)

    def test_password_replaces_an_existing_admin_password(self) -> None:
        """A volume from an older image holds admin/adminadmin12."""
        calls, _ = self.start({"FILEBROWSER_PASSWORD": SECRET},
                              db_exists=True, FB_HAS_ADMIN="1")
        self.assertFalse(any("config init" in c for c in calls))
        self.assertTrue(any(f"users update admin --password {SECRET}" in c for c in calls))
        self.assertTrue(self.served(calls))

    def test_rejected_password_does_not_start_and_is_masked(self) -> None:
        calls, out = self.start({"FILEBROWSER_PASSWORD": SECRET},
                                db_exists=True, FB_HAS_ADMIN="1", FB_FAIL="users update")
        self.assertFalse(self.served(calls))
        self.assertIn("was not started", out)
        self.assertIn("<FILEBROWSER_PASSWORD>", out)
        self.assertNotIn(SECRET, out)

    def test_disable_auth_runs_noauth(self) -> None:
        calls, out = self.start({"FILEBROWSER_DISABLE_AUTH": "true"},
                                db_exists=True, FB_HAS_ADMIN="1")
        self.assertTrue(any("--auth.method=noauth" in c for c in calls))
        self.assertFalse(any("users update" in c for c in calls),
                         "the stored password is kept for when the opt-out goes")
        self.assertTrue(self.served(calls))
        self.assertIn("NO authentication", out)

    def test_disable_auth_requires_the_exact_string_true(self) -> None:
        calls, _ = self.start({"FILEBROWSER_DISABLE_AUTH": "1"}, db_exists=True)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
