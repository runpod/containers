"""runpod/vllm auth middleware and start.sh gate, run against the real files."""

import asyncio
import importlib.util
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "official-templates/vllm"
MIDDLEWARE = TEMPLATE / "scripts/runpod_vllm_auth.py"
START = TEMPLATE / "scripts/start.sh"

KEY = "s3cret-key-value"


def load_middleware():
    spec = importlib.util.spec_from_file_location("runpod_vllm_auth", MIDDLEWARE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recorder:

    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def request(app, path, *, method="GET", auth=None, kind="http", root_path=""):
    headers = [(b"host", b"pod")]
    if auth is not None:
        headers.append((b"authorization", auth.encode("latin-1")))
    scope = {
        "type": kind,
        "method": method,
        "path": path,
        "root_path": root_path,
        "headers": headers,
    }
    events = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event):
        events.append(event)

    asyncio.run(app(scope, receive, send))
    for event in events:
        if event["type"] == "http.response.start":
            return event["status"], events
        if event["type"] == "websocket.close":
            return event["code"], events
    return None, events


class Middleware(unittest.TestCase):
    def setUp(self):
        with mock.patch.dict(os.environ, {"VLLM_API_KEY": KEY}, clear=True):
            module = load_middleware()
            self.inner = Recorder()
            self.app = module.BearerAuth(self.inner)

    def assert_open(self, path, **kw):
        status, _ = request(self.app, path, **kw)
        self.assertEqual(status, 200, f"{path} should be reachable")

    def assert_closed(self, path, **kw):
        before = len(self.inner.calls)
        status, _ = request(self.app, path, **kw)
        self.assertEqual(status, 401, f"{path} should need the key")
        self.assertEqual(len(self.inner.calls), before, f"{path} reached vLLM")

    def test_probes_are_open_without_a_key(self):
        for path in ("/health", "/ping", "/metrics"):
            self.assert_open(path)
        self.assert_open("/ping", method="POST")

    def test_routes_vllm_itself_leaves_open_need_the_key(self):
        for path in (
            "/invocations",
            "/tokenize",
            "/detokenize",
            "/scale_elastic_ep",
            "/checkpoint/save",
            "/version",
            "/docs",
            "/openapi.json",
            "/load",
            "/",
        ):
            self.assert_closed(path, method="POST")

    def test_an_unknown_route_needs_the_key(self):
        self.assert_closed("/some_route_added_in_a_future_release")

    def test_v1_needs_the_key(self):
        self.assert_closed("/v1/chat/completions", method="POST")
        self.assert_closed("/v1/models")

    def test_allowlist_is_exact(self):
        for path in ("/health/", "/healthz", "/metrics/x", "/metricsfoo", "/pingx", "//health"):
            self.assert_closed(path)

    def test_the_right_key_opens_everything(self):
        for path in ("/v1/chat/completions", "/invocations", "/tokenize"):
            self.assert_open(path, method="POST", auth=f"Bearer {KEY}")
        self.assert_open("/invocations", method="POST", auth=f"bearer {KEY}")

    def test_wrong_or_malformed_credentials_are_refused(self):
        for auth in (
            "Bearer wrong",
            f"Bearer {KEY}x",
            f"Basic {KEY}",
            KEY,
            "Bearer ",
            "",
        ):
            self.assert_closed("/invocations", method="POST", auth=auth)

    def test_401_says_so_in_json(self):
        status, events = request(self.app, "/invocations", method="POST")
        self.assertEqual(status, 401)
        start, body = events
        self.assertIn((b"www-authenticate", b"Bearer"), start["headers"])
        self.assertEqual(body["body"], b'{"error": "Unauthorized"}')

    def test_cors_preflight_passes_through(self):
        self.assert_open("/v1/chat/completions", method="OPTIONS")

    def test_websocket_without_key_is_closed_before_accept(self):
        before = len(self.inner.calls)
        code, _ = request(self.app, "/v1/realtime", kind="websocket")
        self.assertEqual(code, 1008)
        self.assertEqual(len(self.inner.calls), before)

    def test_websocket_with_key_reaches_vllm(self):
        request(self.app, "/v1/realtime", kind="websocket", auth=f"Bearer {KEY}")
        self.assertEqual(self.inner.calls[-1]["path"], "/v1/realtime")

    def test_root_path_is_stripped_like_vllm_does(self):
        self.assert_open("/api/health", root_path="/api")
        self.assert_closed("/api/invocations", root_path="/api")

    def test_lifespan_passes_through(self):
        async def run():
            await self.app({"type": "lifespan"}, None, None)

        asyncio.run(run())
        self.assertEqual(self.inner.calls[-1]["type"], "lifespan")

    def test_refuses_to_load_without_a_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            module = load_middleware()
            with self.assertRaises(RuntimeError):
                module.BearerAuth(Recorder())


FAKE_VLLM = """#!/bin/bash
{ printf 'ARG %s\\n' "$@"
  printf 'ENV_KEY %s\\n' "${VLLM_API_KEY-<unset>}"
  printf 'ENV_PYTHONPATH %s\\n' "${PYTHONPATH-<unset>}"
} > "$RECORD"
"""


class StartScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "vllm"
        fake.write_text(FAKE_VLLM)
        fake.chmod(0o755)
        self.record = self.tmp / "record"
        self.base_env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "RECORD": str(self.record),
        }

    def start(self, env, *cmd):
        return subprocess.run(
            ["bash", str(START), *cmd],
            env={**self.base_env, **env},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def recorded(self):
        lines = self.record.read_text().splitlines()
        args = [line[4:] for line in lines if line.startswith("ARG ")]
        env = dict(line.split(" ", 1) for line in lines if line.startswith("ENV_"))
        return args, env

    def test_key_set_starts_vllm_with_the_middleware(self):
        out = self.start({"VLLM_API_KEY": KEY}, "Qwen/Qwen3-8B", "--dtype", "auto")
        self.assertEqual(out.returncode, 0, out.stderr)
        args, env = self.recorded()
        self.assertEqual(args[:4], ["serve", "Qwen/Qwen3-8B", "--dtype", "auto"])
        self.assertIn("--middleware", args)
        self.assertEqual(args[args.index("--middleware") + 1], "runpod_vllm_auth.BearerAuth")
        self.assertTrue(env["ENV_PYTHONPATH"].startswith("/opt/runpod/vllm"))
        self.assertEqual(env["ENV_KEY"], KEY)

    def test_the_key_never_reaches_the_logs(self):
        out = self.start({"VLLM_API_KEY": KEY}, "m")
        self.assertNotIn(KEY, out.stdout + out.stderr)

    def test_host_and_port_are_the_image_s(self):
        self.start({"VLLM_API_KEY": KEY}, "m", "--host", "127.0.0.1", "--port", "9000")
        args, _ = self.recorded()
        self.assertEqual(args[-4:], ["--host", "0.0.0.0", "--port", "8000"])

    def test_pasted_whitespace_is_trimmed_from_the_key(self):
        self.start({"VLLM_API_KEY": f"  {KEY}\n"}, "m")
        _, env = self.recorded()
        self.assertEqual(env["ENV_KEY"], KEY)

    def test_there_is_no_unauthenticated_mode(self):
        """The removed VLLM_DISABLE_AUTH opt-out must not start vLLM keyless."""
        self.assert_refuses({"VLLM_DISABLE_AUTH": "true"})

    def test_neither_set_does_not_start_vllm_and_says_why(self):
        self.assert_refuses({})
        self.assert_refuses({"VLLM_API_KEY": "   "})

    def test_empty_start_command_does_not_start_vllm(self):
        """`vllm serve` with no model exits at once: a restart loop on Runpod."""
        self.assert_refuses({"VLLM_API_KEY": KEY}, cmd=(),
                            reason="the container start command is empty")

    def test_ssh_setup_is_skipped_when_not_root(self):
        out = self.start({"VLLM_API_KEY": KEY}, "m")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("sshd", out.stdout + out.stderr)

    def test_api_key_on_cmd_is_flagged(self):
        out = self.start({"VLLM_API_KEY": KEY}, "m", "--api-key", "other")
        self.assertIn("--api-key is set in the container command", out.stdout)

    def assert_refuses(self, env, cmd=("m",), reason="VLLM_API_KEY is not set"):
        if self.record.exists():
            self.record.unlink()
        proc = subprocess.Popen(
            ["bash", str(START), *cmd],
            env={**self.base_env, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            output = ""
            while output.count("=" * 60) < 2 and time.monotonic() < deadline:
                output += proc.stdout.readline()
            self.assertIn(f"vLLM was NOT started: {reason}", output)
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), "start.sh exited; Runpod would restart it in a loop")
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=10), 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
        self.assertFalse(self.record.exists(), f"vllm ran with env {env}")


if __name__ == "__main__":
    unittest.main()
