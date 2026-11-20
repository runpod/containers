"""The ComfyUI start.sh rules for ComfyUI's password, FileBrowser's password,
ComfyUI-Manager's security settings and user-supplied ComfyUI arguments.

Like test_jupyter_contract, each test runs the real shell function pulled out
of official-templates/comfyui/scripts/start.sh, with fakes on PATH where it
calls out, and checks what it did. ComfyUI and FileBrowser require a
password unless their *_DISABLE_AUTH flag is set: the flag wins over a set
password, any non-empty password is enforced, and with neither the service
does not start. No password ever reaches the output, which is the pod log.
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


TRUE_VALUES = ("true", "1", "yes", "TRUE", "True", "Yes", "YES")
NOT_TRUE_VALUES = ("", "false", "0", "no", "off", "FALSE", "nope", " true", "truee", "2")


class IsTrue(Sandbox):
    def test_values(self) -> None:
        for value, expected in ([(v, 0) for v in TRUE_VALUES]
                                + [(v, 1) for v in NOT_TRUE_VALUES]):
            with self.subTest(value=value):
                result = self.run_bash(function("is_true") + '\nis_true "$V"', {"V": value})
                self.assertEqual(result.returncode, expected)


class ComfyUIAuthMode(Sandbox):
    def mode(self, env: dict) -> tuple[str, str]:
        result = self.run_bash(
            function("is_true") + "\n" + function("resolve_comfyui_auth")
            + '\nresolve_comfyui_auth\necho "MODE=$COMFYUI_AUTH_MODE"', env)
        mode = re.search(r"^MODE=(\w*)$", result.stdout, re.M).group(1)
        return mode, result.stdout + result.stderr

    def test_short_password_puts_the_proxy_in_front(self) -> None:
        """No minimum length: any non-empty password is the password."""
        for password in ("a", "x" * 11, "x" * 12):
            with self.subTest(length=len(password)):
                self.assertEqual(self.mode({"COMFYUI_PASSWORD": password})[0], "proxy")

    def test_password_puts_the_proxy_in_front(self) -> None:
        mode, out = self.mode({"COMFYUI_PASSWORD": SECRET})
        self.assertEqual(mode, "proxy")
        self.assertNotIn(SECRET, out)

    def test_neither_variable_does_not_start_comfyui(self) -> None:
        self.assertEqual(self.mode({})[0], "off")
        self.assertEqual(self.mode({"COMFYUI_PASSWORD": ""})[0], "off")

    def test_disable_flag_turns_auth_off(self) -> None:
        for value in TRUE_VALUES:
            with self.subTest(value=value):
                self.assertEqual(self.mode({"COMFYUI_DISABLE_AUTH": value})[0], "disabled")

    def test_disable_flag_wins_over_a_set_password(self) -> None:
        """The platform may generate a password; the flag still turns auth off."""
        mode, out = self.mode({"COMFYUI_DISABLE_AUTH": "true", "COMFYUI_PASSWORD": SECRET})
        self.assertEqual(mode, "disabled")
        self.assertNotIn(SECRET, out)

    def test_other_flag_values_do_not_turn_auth_off(self) -> None:
        for value in NOT_TRUE_VALUES:
            with self.subTest(value=value):
                self.assertEqual(self.mode({"COMFYUI_DISABLE_AUTH": value})[0], "off")
                self.assertEqual(self.mode({"COMFYUI_DISABLE_AUTH": value,
                                            "COMFYUI_PASSWORD": SECRET})[0], "proxy")


class MainProgram(unittest.TestCase):
    """The parts of the main program that are not functions, read as text."""

    text = SCRIPT.read_text()

    def test_off_holds_the_pod_before_comfyui_setup(self) -> None:
        gate = re.search(
            r'^if \[ "\$COMFYUI_AUTH_MODE" = off \]; then\n(.*?)^fi$',
            self.text, re.S | re.M)
        self.assertIsNotNone(gate, "the COMFYUI_AUTH_MODE=off gate is gone")
        self.assertIn("COMFYUI_PASSWORD is not set", gate.group(1))
        self.assertIn("COMFYUI_DISABLE_AUTH=true", gate.group(1))
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

    def test_no_auth_warns_once(self) -> None:
        gate = re.search(
            r'^if \[ "\$COMFYUI_AUTH_MODE" = disabled \]; then\n(.*?)^fi$',
            self.text, re.S | re.M)
        self.assertIsNotNone(gate, "the COMFYUI_AUTH_MODE=disabled warning is gone")
        warnings = [line for line in gate.group(1).splitlines() if "WARNING" in line]
        self.assertEqual(len(warnings), 1)
        self.assertIn("NO password", warnings[0])
        self.assertLess(gate.start(), self.text.index("\nupgrade_comfyui_if_needed\n"))

    def test_proxy_only_starts_in_proxy_mode(self) -> None:
        start = re.search(
            r'^if \[ "\$COMFYUI_AUTH_MODE" = proxy \]; then\n(.*?)^fi$',
            self.text, re.S | re.M)
        self.assertIsNotNone(start, "the proxy start is no longer gated on proxy mode")
        self.assertIn("run_auth_proxy &", start.group(1))
        self.assertEqual(self.text.count("run_auth_proxy &"), 1)

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
        parser.add_argument("--enable-manager", action="store_true")
        parser.add_argument("--enable-manager-legacy-ui", action="store_true")
        return parser.parse_args(args)

    def test_comfyui_is_loopback_only_behind_the_proxy(self) -> None:
        args, port = self.build("proxy", "")
        self.assertEqual(port, "18188")
        parsed = self.parse(args)
        self.assertEqual((parsed.listen, parsed.port), ("127.0.0.1", 18188))

    def test_disabled_serves_comfyui_on_the_public_port(self) -> None:
        """With auth off there is no proxy: ComfyUI itself listens on 8188.
        The args file still cannot move it."""
        for content in ("", "--listen 127.0.0.1 --port 9000", "--lis=::1"):
            with self.subTest(content=content):
                args, port = self.build("disabled", content)
                self.assertEqual(port, "8188")
                parsed = self.parse(args)
                self.assertEqual((parsed.listen, parsed.port), ("0.0.0.0", 8188))

    def test_only_disabled_puts_comfyui_on_the_network(self) -> None:
        for mode in ("proxy", "off", "Disabled", ""):
            with self.subTest(mode=mode):
                args, port = self.build(mode, "")
                self.assertEqual(port, "18188")
                parsed = self.parse(args)
                self.assertEqual((parsed.listen, parsed.port), ("127.0.0.1", 18188))

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

    def run_loop(self, script: str, overrides: str = "") -> tuple[subprocess.CompletedProcess, list[str]]:
        runs = self.work / "runs"
        fake = self.bin / "fake-python"
        fake.write_text(f"#!/bin/bash\necho run >> {runs}\nn=$(wc -l < {runs})\n{script}")
        fake.chmod(0o755)
        result = self.run_bash(
            constants("COMFYUI_PUBLIC_PORT", "COMFYUI_INTERNAL_PORT",
                      "AUTH_PROXY_MAX_FAST_FAILURES",
                      "AUTH_PROXY_FAST_FAILURE_SECONDS")
            + overrides
            + function("run_auth_proxy") + "\nrun_auth_proxy",
            {"SYSTEM_PYTHON": str(fake), "AUTH_PROXY": "proxy.py",
             "AUTH_PROXY_RESTART_DELAY": "0", "COMFYUI_PASSWORD": SECRET})
        return result, runs.read_text().splitlines()

    def test_gives_up_after_repeated_fast_failures(self) -> None:
        """A cause the proxy cannot report as 2 (port in use) must not loop
        forever, logging a warning every few seconds."""
        result, runs = self.run_loop("exit 1\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(runs), 5)
        self.assertEqual(result.stdout.count("restarting it"), 4)
        self.assertIn("giving up", result.stdout)

    def test_a_long_run_resets_the_count(self) -> None:
        """Runs that lived past the fast-failure window are crashes worth
        restarting; only consecutive fast exits count towards giving up."""
        # Runs 1-4 die at once, run 5 outlives a 1s window, runs 6-9 die at
        # once, run 10 refuses its config. Without the reset, 8 fast exits
        # would have given up at run 5.
        result, runs = self.run_loop(
            '[ "$n" -eq 5 ] && sleep 2.2\n[ "$n" -ge 10 ] && exit 2\nexit 1\n',
            overrides="AUTH_PROXY_FAST_FAILURE_SECONDS=1\n")
        self.assertEqual(len(runs), 10)
        self.assertIn("refused to start", result.stdout)
        self.assertNotIn("giving up", result.stdout)


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


class ImageManagerWins(Sandbox):
    """comfyui_manager is patched in the image. The venv is created with
    --system-site-packages, so a copy installed into it comes first on sys.path
    and would run a Manager with none of the Runpod fixes. Nothing on the
    startup path may put one there, whatever the workspace ComfyUI pins."""

    def fake_python(self, freeze: str, probe_exit: int, version: str = "4.2.2") -> Path:
        log = self.work / "python.log"
        (self.bin / "python").write_text(f"""#!/bin/bash
printf '%s\\n' "$*" >> {log}
case "$*" in
    "-m pip freeze")        printf '%b' {freeze!r} ;;
    "-m pip install"*)      ;;
    "-m pip uninstall"*)    ;;
    "-c "*)                 echo {version} ;;
    "-")                    cat > /dev/null; exit {probe_exit} ;;
esac
exit 0
""")
        (self.bin / "python").chmod(0o755)
        return log

    def comfyui_dir(self, requirements: str, manager_pin: str) -> Path:
        comfyui = self.work / "ComfyUI"
        comfyui.mkdir(exist_ok=True)
        (comfyui / "requirements.txt").write_text(requirements)
        (comfyui / "manager_requirements.txt").write_text(manager_pin)
        return comfyui

    def sync(self, requirements: str, manager_pin: str, freeze: str):
        log = self.fake_python(freeze, probe_exit=1)
        comfyui = self.comfyui_dir(requirements, manager_pin)
        result = self.run_bash(
            "run_with_heartbeat() { shift; \"$@\"; }\n"
            + function("sync_comfyui_pinned_packages")
            + "\nsync_comfyui_pinned_packages",
            {"COMFYUI_DIR": str(comfyui), "VENV_DIR": str(self.work / "venv")})
        return log.read_text() if log.exists() else "", result.stdout + result.stderr

    def test_a_manager_pin_is_never_installed_into_the_venv(self) -> None:
        """The workspace moved ahead and asks for a newer Manager. Other pins
        are still installed; the Manager pin is not."""
        calls, out = self.sync(
            requirements="comfy-kitchen==2.0.0\n",
            manager_pin="comfyui_manager==4.3.0\n",
            freeze="comfy-kitchen==1.0.0\ncomfyui-manager==4.2.2\n")
        self.assertIn("comfy-kitchen==2.0.0", calls)
        self.assertNotIn("comfyui_manager", calls)
        self.assertNotIn("comfyui-manager", calls)
        self.assertNotIn("4.3.0", calls)

    def test_a_matching_manager_pin_is_not_installed_either(self) -> None:
        calls, _ = self.sync(
            requirements="comfy-kitchen==1.0.0\n",
            manager_pin="comfyui_manager==4.2.2\n",
            freeze="comfy-kitchen==1.0.0\n")
        self.assertNotIn("pip install", calls)

    def test_a_venv_copy_is_removed(self) -> None:
        log = self.fake_python("", probe_exit=0)
        comfyui = self.comfyui_dir("", "comfyui_manager==4.2.2\n")
        self.run_bash(
            function("pin_image_manager") + "\npin_image_manager",
            {"COMFYUI_DIR": str(comfyui), "VENV_DIR": str(self.work / "venv")})
        self.assertIn("-m pip uninstall -y comfyui_manager", log.read_text())

    def test_no_venv_copy_means_no_uninstall(self) -> None:
        log = self.fake_python("", probe_exit=1)
        comfyui = self.comfyui_dir("", "comfyui_manager==4.2.2\n")
        self.run_bash(
            function("pin_image_manager") + "\npin_image_manager",
            {"COMFYUI_DIR": str(comfyui), "VENV_DIR": str(self.work / "venv")})
        self.assertNotIn("uninstall", log.read_text())

    def test_a_differing_pin_is_reported_not_installed(self) -> None:
        log = self.fake_python("", probe_exit=1, version="4.2.2")
        comfyui = self.comfyui_dir("", "comfyui_manager==4.3.0\n")
        result = self.run_bash(
            function("pin_image_manager") + "\npin_image_manager",
            {"COMFYUI_DIR": str(comfyui), "VENV_DIR": str(self.work / "venv")})
        out = result.stdout + result.stderr
        self.assertIn("asks for ComfyUI-Manager 4.3.0", out)
        self.assertIn("this image ships 4.2.2", out)
        self.assertNotIn("pip install", log.read_text())


class FileBrowser(Sandbox):
    def start(self, env: dict, db_exists: bool = False, **fake) -> tuple[list, str]:
        fake_bin = self.bin / "filebrowser"
        fake_bin.write_text(FAKE_FILEBROWSER)
        fake_bin.chmod(0o755)
        record = self.work / "argv"
        db = self.work / "filebrowser.db"
        if db_exists:
            db.write_text("")
        funcs = (function("is_true") + "\n" + function("filebrowser_cli") + "\n"
                 + function("start_filebrowser")
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
        self.assertIn("FILEBROWSER_DISABLE_AUTH=true", out)
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

    def test_no_minimum_length(self) -> None:
        """FileBrowser's own floor is 12 by default; it is set to 1 before
        admin's password is set, so any non-empty password works."""
        for db_exists in (False, True):
            with self.subTest(db_exists=db_exists):
                (self.work / "argv").unlink(missing_ok=True)
                calls, _ = self.start({"FILEBROWSER_PASSWORD": "ab"}, db_exists=db_exists,
                                      FB_HAS_ADMIN="1" if db_exists else "")
                floor = [i for i, c in enumerate(calls) if "--minimumPasswordLength=1" in c]
                user = [i for i, c in enumerate(calls) if "users add" in c or "users update" in c]
                self.assertTrue(floor and user, calls)
                self.assertLess(floor[0], user[0])
                self.assertTrue(self.served(calls))

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

    def test_disable_flag_serves_with_no_login(self) -> None:
        for value in TRUE_VALUES:
            with self.subTest(value=value):
                (self.work / "argv").unlink(missing_ok=True)
                calls, out = self.start({"FILEBROWSER_DISABLE_AUTH": value},
                                        db_exists=True, FB_HAS_ADMIN="1")
                self.assertTrue(any("--auth.method=noauth" in c for c in calls), calls)
                self.assertFalse(any("--auth.method=json" in c for c in calls))
                self.assertFalse(any("users update" in c or "users add" in c for c in calls))
                self.assertTrue(self.served(calls))
                self.assertEqual(out.count("WARNING"), 1, out)
                self.assertIn("NO login", out)

    def test_disable_flag_wins_over_a_set_password(self) -> None:
        calls, out = self.start({"FILEBROWSER_PASSWORD": SECRET, "FILEBROWSER_DISABLE_AUTH": "1"},
                                db_exists=True, FB_HAS_ADMIN="1")
        self.assertTrue(any("--auth.method=noauth" in c for c in calls))
        self.assertTrue(self.served(calls))
        self.assertNotIn(SECRET, out)

    def test_disable_flag_on_a_new_volume_creates_admin(self) -> None:
        """noauth signs everyone in as user 1, so admin must exist. Its
        password is random and never printed."""
        calls, out = self.start({"FILEBROWSER_DISABLE_AUTH": "yes"})
        add = [c for c in calls if c.startswith("-d ") and " users add admin " in c]
        self.assertEqual(len(add), 1, calls)
        password = add[0].split(" users add admin ")[1].split(" --perm.admin")[0]
        self.assertGreaterEqual(len(password), 20)
        self.assertNotIn(password, out)
        self.assertTrue(self.served(calls))

    def test_other_flag_values_keep_the_login(self) -> None:
        for value in NOT_TRUE_VALUES:
            with self.subTest(value=value):
                (self.work / "argv").unlink(missing_ok=True)
                calls, _ = self.start({"FILEBROWSER_DISABLE_AUTH": value},
                                      db_exists=True, FB_HAS_ADMIN="1")
                self.assertEqual(calls, [])
                calls, _ = self.start({"FILEBROWSER_DISABLE_AUTH": value,
                                       "FILEBROWSER_PASSWORD": SECRET},
                                      db_exists=True, FB_HAS_ADMIN="1")
                self.assertTrue(any("--auth.method=json" in c for c in calls))
                self.assertFalse(any("noauth" in c for c in calls))

    def test_login_is_forced_back_on(self) -> None:
        """A database left on noauth, by an earlier start with the flag or by
        hand, is switched back to a login once the flag is gone."""
        calls, _ = self.start({"FILEBROWSER_PASSWORD": SECRET},
                              db_exists=True, FB_HAS_ADMIN="1")
        self.assertTrue(any("--auth.method=json" in c for c in calls))
        self.assertFalse(any("noauth" in c for c in calls))
        self.assertTrue(any(f"users update admin --password {SECRET}" in c for c in calls))
        self.assertTrue(self.served(calls))


if __name__ == "__main__":
    unittest.main()
