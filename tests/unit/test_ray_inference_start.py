"""The ray-cluster inference variant's start script and node wait.

start.sh runs whole, with fakes on PATH for nvidia-smi, vllm, curl and
LiteLLM, and fake wait_for_nodes.py and download_model.py; the test records
what each was run with. Its fixed paths (/opt/runpod/inference, /etc/litellm, LiteLLM's binary)
point into a sandbox, and `exec /start.sh` becomes "say so, wait for the
background jobs, then stop", so every path ends where the pod would hand off
to /start.sh. Every refusal is checked to start nothing; every acceptance, for
the exact vllm command line and LiteLLM's key.

wait_for_nodes.py runs against a fake `ray` module, and download_model.py's
choice of files against fake repo listings.
"""

import fnmatch
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
INFERENCE = REPO_ROOT / "official-templates/ray-cluster/inference"
SCRIPT = INFERENCE / "start.sh"
WAIT_FOR_NODES = INFERENCE / "wait_for_nodes.py"
DOWNLOAD_MODEL = INFERENCE / "download_model.py"
KEY = "pod-secret-value-1234"
MODEL = "Qwen/Qwen3-0.6B"
HANDOFF = "[test] handed off to /start.sh"
SERVICES = "[test] /start.sh started"

# Fakes. Each records its arguments NUL-separated, so a quoted argument with
# spaces stays one.
FAKE_VLLM = r"""#!/bin/bash
printf '%s\0' "$@" > "$WORK/vllm.args"
env > "$WORK/vllm.env"
[[ -e "$WORK/download.args" ]] && : > "$WORK/vllm.after_download"
[[ -n "${FAKE_VLLM_FAIL:-}" ]] && exit 1
sleep 1
"""
FAKE_LITELLM = r"""#!/bin/bash
printf '%s\0' "$@" > "$WORK/litellm.args"
env > "$WORK/litellm.env"
"""
# Fails like a refused connection while vLLM is down.
FAKE_CURL = r"""#!/bin/bash
[[ -n "${FAKE_CURL_FAIL:-}" ]] && exit 7
exit 0
"""
# No FAKE_GPUS: like a pod without the NVIDIA runtime, nvidia-smi fails.
FAKE_NVIDIA_SMI = r"""#!/bin/bash
[[ -n "${FAKE_GPUS:-}" ]] || exit 9
for ((i = 0; i < FAKE_GPUS; i++)); do echo "GPU $i: NVIDIA H100 (UUID: GPU-$i)"; done
"""
# Slow enough that /start.sh, which must not wait for it, starts first.
FAKE_WAIT_FOR_NODES = r"""import os, sys, time
time.sleep(float(os.environ.get("FAKE_WAIT_S", "0")))
print("[fake] all nodes joined", file=sys.stderr, flush=True)
open(os.path.join(os.environ["WORK"], "wait_for_nodes.args"), "w").write(" ".join(sys.argv[1:]))
print(os.environ.get("FAKE_NODE_GPUS", "8"))
sys.exit(int(os.environ.get("FAKE_WAIT_RC", "0")))
"""
FAKE_DOWNLOAD_MODEL = r"""import os, sys
open(os.path.join(os.environ["WORK"], "download.args"), "w").write("".join(a + "\0" for a in sys.argv[1:]))
open(os.path.join(os.environ["WORK"], "download.env"), "w").write("".join(f"{k}={v}\n" for k, v in os.environ.items()))
if os.environ.get("FAKE_DOWNLOAD_FAIL"):
    sys.exit("[ray-inference] RepositoryNotFoundError: 404")
"""


def sandboxed_script(work: Path) -> str:
    """start.sh with its fixed paths moved into `work`. Fails if one of the
    lines it rewrites is gone: update this test, the rule still has to hold."""
    text = SCRIPT.read_text()
    for old, new in [
        ("readonly INFERENCE_DIR=/opt/runpod/inference", f"readonly INFERENCE_DIR={work}/inference"),
        ("readonly LITELLM=/opt/litellm/bin/litellm", f"readonly LITELLM={work}/bin/litellm"),
        ("readonly LITELLM_DIR=/etc/litellm", f"readonly LITELLM_DIR={work}/litellm"),
        ("services() { exec /start.sh; }",
         f'services() {{ echo "{SERVICES}"; wait; echo "{HANDOFF}"; exit 0; }}'),
    ]:
        if text.count(old) != 1:
            raise AssertionError(f"{SCRIPT}: no single `{old}` line to sandbox.")
        text = text.replace(old, new)
    return text


class StartScript(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        for d in ("bin", "inference"):
            (self.work / d).mkdir()
        for name, body in [("vllm", FAKE_VLLM), ("litellm", FAKE_LITELLM),
                           ("curl", FAKE_CURL), ("nvidia-smi", FAKE_NVIDIA_SMI)]:
            path = self.work / "bin" / name
            path.write_text(body)
            path.chmod(0o755)
        (self.work / "inference/wait_for_nodes.py").write_text(FAKE_WAIT_FOR_NODES)
        (self.work / "inference/download_model.py").write_text(FAKE_DOWNLOAD_MODEL)
        (self.work / "start.sh").write_text(sandboxed_script(self.work))

    def run_start(self, env: dict) -> str:
        result = subprocess.run(
            ["bash", str(self.work / "start.sh")],
            env={"PATH": f"{self.work / 'bin'}:{os.environ['PATH']}",
                 "HOME": str(self.work), "WORK": str(self.work), **env},
            capture_output=True, text=True, timeout=60,
        )
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        self.assertIn(HANDOFF, out, "the script must always end in /start.sh")
        return out

    def recorded(self, name: str) -> list[str] | None:
        path = self.work / name
        return path.read_text().split("\0")[:-1] if path.exists() else None

    def recorded_env(self, name: str) -> dict[str, str]:
        lines = (self.work / name).read_text().splitlines()
        return dict(line.split("=", 1) for line in lines if "=" in line)

    def test_refusals_start_nothing(self) -> None:
        """<description>, <env>, <log line it must report>. Each still hands
        off to /start.sh, so the pod stays up, and runs neither vLLM nor
        LiteLLM, and downloads nothing."""
        serving = {"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1",
                   "FAKE_CURL_FAIL": "1"}
        rows = [
            ("worker node", {**serving, "NODE_RANK": "1"}, "worker node: Ray only"),
            ("no MODEL_REPO", {"LITELLM_MASTER_KEY": KEY}, "MODEL_REPO is not set; skipping vLLM"),
            ("empty MODEL_REPO", {**serving, "MODEL_REPO": ""}, "MODEL_REPO is not set"),
            ("MODEL_REPO read as an option", {**serving, "MODEL_REPO": "--trust-remote-code"},
             "starts with '-'"),
            ("no key at all", {"MODEL_REPO": MODEL, "FAKE_GPUS": "1"},
             "neither LITELLM_MASTER_KEY nor JUPYTER_PASSWORD is set"),
            ("whitespace-only key is no key", {"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": " \t ",
                                               "FAKE_GPUS": "1"},
             "neither LITELLM_MASTER_KEY nor JUPYTER_PASSWORD is set"),
            ("--api-key", {**serving, "VLLM_EXTRA_ARGS": f"--api-key {KEY}"}, "sets --api-key"),
            ("--api-key=", {**serving, "VLLM_EXTRA_ARGS": f"--api-key={KEY}"}, "sets --api-key"),
            ("--api_key, vLLM's underscore spelling", {**serving, "VLLM_EXTRA_ARGS": f"--api_key={KEY}"},
             "sets --api-key"),
            ("--api-key hidden in quotes", {**serving, "VLLM_EXTRA_ARGS": f"'--api-key={KEY}'"},
             "sets --api-key"),
            ("--api-key after other args", {**serving, "VLLM_EXTRA_ARGS": f"--enforce-eager --api-key {KEY}"},
             "sets --api-key"),
            ("unbalanced quote", {**serving, "VLLM_EXTRA_ARGS": "--hf-overrides '{\"a\": 1}"},
             "VLLM_EXTRA_ARGS can't be split into arguments"),
            ("no GPU on a plain pod", {**serving, "FAKE_GPUS": ""}, "no GPU visible"),
            ("zero GPUs on a plain pod", {**serving, "FAKE_GPUS": "0"}, "no GPU visible"),
        ]
        for count in ("abc", "0", "0000", "-1", "99999", "1.5", "2; id", "$(id)", " 2"):
            rows.append((f"NUM_NODES={count!r}", {**serving, "NODE_RANK": "0", "NUM_NODES": count},
                         "is not a node count"))
        for what, env, want in rows:
            with self.subTest(what):
                for name in ("vllm.args", "litellm.args", "download.args"):
                    (self.work / name).unlink(missing_ok=True)
                out = self.run_start(env)
                self.assertIn(want, out)
                self.assertIsNone(self.recorded("download.args"), "the model was downloaded")
                self.assertIsNone(self.recorded("vllm.args"), "vLLM was started")
                self.assertIsNone(self.recorded("litellm.args"), "LiteLLM was started")
                self.assertNotIn(KEY, out, "the key reached the log")

    def test_cluster_refusals_after_the_download_start_nothing(self) -> None:
        """Known only once the nodes have joined, after the download: still
        neither vLLM nor LiteLLM."""
        serving = {"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "NODE_RANK": "0",
                   "NUM_NODES": "2", "FAKE_CURL_FAIL": "1"}
        for what, rc, want in [
            ("nodes can't be split evenly", "2", "can't be split into 2 pipeline stages"),
            ("Ray unreachable", "1", "could not read the cluster's nodes from Ray"),
        ]:
            with self.subTest(what):
                for name in ("vllm.args", "litellm.args"):
                    (self.work / name).unlink(missing_ok=True)
                out = self.run_start({**serving, "FAKE_WAIT_RC": rc})
                self.assertIn(want, out)
                self.assertIsNone(self.recorded("vllm.args"), "vLLM was started")
                self.assertIsNone(self.recorded("litellm.args"), "LiteLLM was started")

    def test_start_sh_does_not_wait_for_the_nodes(self) -> None:
        """SSH and Jupyter come up while workers are still joining."""
        out = self.run_start({"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "NODE_RANK": "0",
                              "NUM_NODES": "2", "FAKE_WAIT_S": "2"})
        self.assertLess(out.index(SERVICES), out.index("[fake] all nodes joined"))
        self.assertIsNotNone(self.recorded("vllm.args"))

    def test_vllm_command_line(self) -> None:
        """<description>, <env>, <vllm arguments after `serve <model>` and
        before the fixed --host/--port>."""
        base = {"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "2"}
        rows = [
            ("plain pod: tensor parallel over its GPUs", base, ["--tensor-parallel-size", "2"]),
            ("cluster: pipeline over nodes, tensor over GPUs per node",
             {**base, "NODE_RANK": "0", "NUM_NODES": "2", "FAKE_NODE_GPUS": "4"},
             ["--distributed-executor-backend", "ray", "--pipeline-parallel-size", "2",
              "--tensor-parallel-size", "4"]),
            ("cluster: NUM_NODES leading zeros dropped",
             {**base, "NODE_RANK": "0", "NUM_NODES": "002", "FAKE_NODE_GPUS": "8"},
             ["--distributed-executor-backend", "ray", "--pipeline-parallel-size", "2",
              "--tensor-parallel-size", "8"]),
            ("cluster: NUM_NODES unset is one node", {**base, "NODE_RANK": "0", "FAKE_NODE_GPUS": "8"},
             ["--distributed-executor-backend", "ray", "--pipeline-parallel-size", "1",
              "--tensor-parallel-size", "8"]),
            ("cluster: NUM_NODES upper bound", {**base, "NODE_RANK": "0", "NUM_NODES": "9999",
                                                "FAKE_NODE_GPUS": "1"},
             ["--distributed-executor-backend", "ray", "--pipeline-parallel-size", "9999",
              "--tensor-parallel-size", "1"]),
            ("MAX_MODEL_LENGTH", {**base, "MAX_MODEL_LENGTH": "4096"},
             ["--tensor-parallel-size", "2", "--max-model-len", "4096"]),
            ("extra args follow the derived ones, so they override them",
             {**base, "VLLM_EXTRA_ARGS": "--tensor-parallel-size 1  --enforce-eager"},
             ["--tensor-parallel-size", "2", "--tensor-parallel-size", "1", "--enforce-eager"]),
            ("a quoted JSON value with spaces stays one argument",
             {**base, "VLLM_EXTRA_ARGS": '--speculative-config \'{"method": "ngram", "num_speculative_tokens": 4}\''},
             ["--tensor-parallel-size", "2", "--speculative-config",
              '{"method": "ngram", "num_speculative_tokens": 4}']),
            ("double quotes and escapes, like a shell",
             {**base, "VLLM_EXTRA_ARGS": '--served-model-name "my model" --chat-template a\\ b'},
             ["--tensor-parallel-size", "2", "--served-model-name", "my model", "--chat-template", "a b"]),
            ("nothing is expanded or run",
             {**base, "VLLM_EXTRA_ARGS": "--x $(touch pwned) `touch pwned` $HOME * ;id"},
             ["--tensor-parallel-size", "2", "--x", "$(touch", "pwned)", "`touch", "pwned`",
              "$HOME", "*", ";id"]),
            ("flags that only resemble --api-key pass",
             {**base, "VLLM_EXTRA_ARGS": "--api-key-file=x --served-model-name=--api-key"},
             ["--tensor-parallel-size", "2", "--api-key-file=x", "--served-model-name=--api-key"]),
            ("a --host in the extra args is overridden",
             {**base, "VLLM_EXTRA_ARGS": "--host 0.0.0.0 --port 9000"},
             ["--tensor-parallel-size", "2", "--host", "0.0.0.0", "--port", "9000"]),
        ]
        for what, env, want in rows:
            with self.subTest(what):
                self.run_start(env)
                self.assertEqual(self.recorded("vllm.args"),
                                 ["serve", MODEL, *want, "--host", "127.0.0.1", "--port", "8000"])
                self.assertFalse((self.work / "pwned").exists())
                if "NODE_RANK" in env:
                    self.assertEqual((self.work / "wait_for_nodes.args").read_text(),
                                     str(int(env.get("NUM_NODES", "1"))))

    def test_key(self) -> None:
        """<description>, <env>, <key in master_key and LiteLLM's env, or None
        for no authentication>, <log line>."""
        base = {"MODEL_REPO": MODEL, "FAKE_GPUS": "1"}
        rows = [
            ("LITELLM_MASTER_KEY", {**base, "LITELLM_MASTER_KEY": KEY}, KEY,
             "authentication on (key from LITELLM_MASTER_KEY)"),
            ("pasted whitespace trimmed", {**base, "LITELLM_MASTER_KEY": f" \t{KEY} \n"}, KEY,
             "(key from LITELLM_MASTER_KEY)"),
            ("LITELLM_MASTER_KEY outranks JUPYTER_PASSWORD",
             {**base, "LITELLM_MASTER_KEY": KEY, "JUPYTER_PASSWORD": "jupyter-pw"}, KEY,
             "(key from LITELLM_MASTER_KEY)"),
            ("JUPYTER_PASSWORD fallback, verbatim", {**base, "JUPYTER_PASSWORD": f" {KEY} "}, f" {KEY} ",
             "(key from JUPYTER_PASSWORD)"),
            ("none turns authentication off", {**base, "LITELLM_MASTER_KEY": "none"}, None,
             "warn: LITELLM_MASTER_KEY=none"),
            ("None, any case", {**base, "LITELLM_MASTER_KEY": " NoNe "}, None,
             "warn: LITELLM_MASTER_KEY=none"),
            ("a JUPYTER_PASSWORD of none is a key, not the opt-out",
             {**base, "JUPYTER_PASSWORD": "none"}, "none", "(key from JUPYTER_PASSWORD)"),
            ("key with shell and JSON metacharacters", {**base, "LITELLM_MASTER_KEY": "a'b\"c$(id)`x`\\"},
             "a'b\"c$(id)`x`\\", "(key from LITELLM_MASTER_KEY)"),
        ]
        for what, env, want, log in rows:
            with self.subTest(what):
                out = self.run_start({**env, "VLLM_API_KEY": "leftover"})
                self.assertIn(log, out)
                litellm = self.recorded_env("litellm.env")
                vllm = self.recorded_env("vllm.env")
                self.assertEqual(litellm.get("LITELLM_MASTER_KEY"), want)
                self.assertEqual(litellm.get("LITELLM_DANGEROUSLY_PERMIT_WEAK_OR_UNSET_MASTER_KEY"),
                                 None if want else "true")
                self.assertEqual(litellm.get("DISABLE_ADMIN_UI"), "True")
                self.assertNotIn("LITELLM_MASTER_KEY", vllm, "vLLM doesn't need the key")
                self.assertNotIn("VLLM_API_KEY", vllm, "vLLM would demand a key LiteLLM never sends")
                key_file = self.work / "litellm/master_key"
                self.assertEqual(key_file.read_text(), want or "none")
                self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(key_file.parent.stat().st_mode), 0o700)
                if want and want.strip():
                    self.assertNotIn(want.strip(), out, "the key reached the log")

    def test_litellm_config(self) -> None:
        """One model under MODEL_REPO's own name, valid JSON whatever the
        name holds."""
        for model in (MODEL, 'org/we"ird\\name', "org/{{ template }}: x"):
            with self.subTest(model):
                self.run_start({"MODEL_REPO": model, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1"})
                config = json.loads((self.work / "litellm/config.json").read_text())
                (entry,) = config["model_list"]
                self.assertEqual(entry["model_name"], model)
                self.assertEqual(entry["litellm_params"]["model"], f"hosted_vllm/{model}")
                self.assertEqual(entry["litellm_params"]["api_base"], "http://127.0.0.1:8000/v1")
                self.assertIn("hashed_api_key", config["litellm_settings"]["prometheus_exclude_labels"])
                args = self.recorded("litellm.args")
                self.assertEqual(args[args.index("--port") + 1], "4000")
                self.assertEqual(args[args.index("--config") + 1], str(self.work / "litellm/config.json"))

    def test_download_before_vllm(self) -> None:
        """<description>, <VLLM_EXTRA_ARGS>, <download_model.py's revision,
        cache dir and load format>. Always before vLLM, and without the API
        key."""
        base = {"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1"}
        rows = [
            ("defaults", "", ["", "", "auto"]),
            ("--revision", "--revision abc123", ["abc123", "", "auto"]),
            ("--revision=", "--revision=abc123", ["abc123", "", "auto"]),
            ("--download-dir", "--download-dir /workspace/models", ["", "/workspace/models", "auto"]),
            ("--download_dir=, vLLM's underscore spelling", "--download_dir=/m", ["", "/m", "auto"]),
            ("--load-format", "--load-format mistral --tokenizer-mode mistral", ["", "", "mistral"]),
            ("--load_format=", "--load_format=gguf", ["", "", "gguf"]),
            ("the last one wins, as in vLLM", "--revision a --enforce-eager --revision=b", ["b", "", "auto"]),
            ("a trailing --revision with no value", "--revision", ["", "", "auto"]),
        ]
        for what, extra, want in rows:
            with self.subTest(what):
                for name in ("download.args", "vllm.after_download"):
                    (self.work / name).unlink(missing_ok=True)
                out = self.run_start({**base, "VLLM_EXTRA_ARGS": extra})
                self.assertEqual(self.recorded("download.args"), [MODEL, *want])
                self.assertTrue((self.work / "vllm.after_download").exists(), "vLLM started first")
                self.assertNotIn("LITELLM_MASTER_KEY", self.recorded_env("download.env"))
                self.assertIn(f"downloading {MODEL}", out)

    def test_local_directory_is_not_downloaded(self) -> None:
        model = str(self.work / "models/local")
        Path(model).mkdir(parents=True)
        self.run_start({"MODEL_REPO": model, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1"})
        self.assertIsNone(self.recorded("download.args"))
        self.assertEqual(self.recorded("vllm.args")[:2], ["serve", model])

    def test_failed_download_starts_nothing(self) -> None:
        out = self.run_start({"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1",
                              "FAKE_DOWNLOAD_FAIL": "1", "FAKE_CURL_FAIL": "1"})
        self.assertIn("RepositoryNotFoundError", out)
        self.assertIn(f"could not download {MODEL}", out)
        self.assertIn("vLLM exited before it was ready, so LiteLLM was not started", out)
        self.assertIsNone(self.recorded("vllm.args"))
        self.assertIsNone(self.recorded("litellm.args"))

    def test_vllm_exiting_before_ready_skips_litellm(self) -> None:
        out = self.run_start({"MODEL_REPO": MODEL, "LITELLM_MASTER_KEY": KEY, "FAKE_GPUS": "1",
                              "FAKE_VLLM_FAIL": "1", "FAKE_CURL_FAIL": "1"})
        self.assertIn("vLLM exited with status 1", out)
        self.assertIn("vLLM exited before it was ready, so LiteLLM was not started", out)
        self.assertIsNone(self.recorded("litellm.args"))


def load_wait_for_nodes(snapshots: list[list[dict]]) -> types.ModuleType:
    """wait_for_nodes.py with a fake `ray` whose nodes() returns each snapshot
    in turn, then the last one forever."""
    ray = types.ModuleType("ray")
    ray.init = lambda **_: None
    calls = iter(snapshots)
    last = []

    def nodes() -> list[dict]:
        nonlocal last
        last = next(calls, last)
        return last

    ray.nodes = nodes
    with mock.patch.dict(sys.modules, {"ray": ray}):
        spec = importlib.util.spec_from_file_location("wait_for_nodes", WAIT_FOR_NODES)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def node(gpus: int | None, alive: bool = True) -> dict:
    return {"Alive": alive, "Resources": {} if gpus is None else {"GPU": float(gpus), "CPU": 8.0}}


class WaitForNodes(unittest.TestCase):
    def test_shape_error(self) -> None:
        """<description>, <GPUs per alive node>, <NUM_NODES>, <error match or None>."""
        shape_error = load_wait_for_nodes([]).shape_error
        rows = [
            ("one node", [8], 1, None),
            ("equal nodes", [8, 8, 8, 8], 4, None),
            ("one GPU each", [1, 1], 2, None),
            ("more nodes than NUM_NODES", [8, 8, 8], 2, "3 nodes are in Ray but NUM_NODES is 2"),
            ("fewer nodes than NUM_NODES", [8], 2, "1 nodes are in Ray but NUM_NODES is 2"),
            ("uneven GPU counts", [8, 4], 2, "GPUs per node differ"),
            ("a node without GPUs", [8, 0], 2, "GPUs per node differ or are missing"),
            ("no node has GPUs", [0, 0], 2, "are missing"),
        ]
        for what, gpus, want, error in rows:
            with self.subTest(what):
                got = shape_error(gpus, want)
                if error is None:
                    self.assertIsNone(got)
                else:
                    self.assertIn(error, got)

    def run_main(self, snapshots: list[list[dict]], want: int) -> tuple[int, str, str]:
        module = load_wait_for_nodes(snapshots)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["wait_for_nodes.py", str(want)]), \
                mock.patch.object(module.time, "sleep"), redirect_stdout(out), redirect_stderr(err):
            rc = module.main()
        return rc, out.getvalue(), err.getvalue()

    def test_waits_for_every_node_then_prints_gpus_per_node(self) -> None:
        rc, out, err = self.run_main([[node(4)], [node(4), node(4, alive=False)], [node(4), node(4)]], 2)
        self.assertEqual((rc, out), (0, "4\n"))
        self.assertIn("1 of 2 nodes have joined Ray", err)

    def test_shape_error_exits_2_and_prints_nothing(self) -> None:
        """stdout is the GPU count start.sh reads; on an error it stays empty."""
        for what, snapshot, want in [
            ("uneven", [node(8), node(4)], 2),
            ("a CPU-only node", [node(8), node(None)], 2),
            ("too many nodes", [node(8), node(8), node(8)], 2),
        ]:
            with self.subTest(what):
                rc, out, err = self.run_main([snapshot], want)
                self.assertEqual((rc, out), (2, ""))
                self.assertTrue(err)


def load_download_model() -> types.ModuleType:
    """download_model.py with a fake huggingface_hub (it runs in the image)."""
    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = hub.list_repo_files = hub.snapshot_download = None
    with mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
        spec = importlib.util.spec_from_file_location("download_model", DOWNLOAD_MODEL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def kept(files: list[str], allow: list[str], ignore: list[str]) -> list[str]:
    """What snapshot_download keeps of `files` (huggingface_hub matches with
    fnmatch, as here)."""
    return [f for f in files
            if any(fnmatch.fnmatch(f, p) for p in allow) and not any(fnmatch.fnmatch(f, p) for p in ignore)]


class DownloadModel(unittest.TestCase):
    module = load_download_model()

    def test_the_weights_vllm_downloads(self) -> None:
        """<description>, <repo files>, <load format>, <files the safetensors
        index maps, or None>, <weights kept, or None to leave them to vLLM>."""
        config = ["config.json", "tokenizer.json", "README.md"]
        shards = ["model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"]
        rows = [
            ("safetensors over bin and pt",
             ["model.safetensors", "pytorch_model.bin", "model.pt", "tf_model.h5", "onnx/model.onnx"],
             "auto", None, ["model.safetensors"]),
            ("the index's shards only", [*shards, "model-extra.safetensors", "pytorch_model.bin"],
             "auto", shards, shards),
            ("bin when there is no safetensors", ["pytorch_model.bin", "model.pt"], "auto", None,
             ["pytorch_model.bin"]),
            ("pt last", ["model.pt", "tf_model.h5"], "auto", None, ["model.pt"]),
            ("a consolidated copy makes auto Mistral's format (Mistral's repos)",
             ["consolidated.safetensors", *shards, "params.json"], "auto", shards,
             ["consolidated.safetensors"]),
            ("--load-format safetensors reads the index instead",
             ["consolidated.safetensors", *shards], "safetensors", shards, shards),
            ("--load-format mistral", ["consolidated.safetensors", *shards], "mistral", shards,
             ["consolidated.safetensors"]),
            ("--load-format pt", ["model.safetensors", "model.pt"], "pt", None, ["model.pt"]),
            ("original/ is ignored, as vLLM's default --ignore-patterns does",
             ["original/sub/model.safetensors", "original/consolidated.00.pth", "model.safetensors"],
             "auto", None, ["model.safetensors"]),
            ("weights only in subfolders: left to vLLM", ["sub/model.safetensors"], "auto", None, None),
            ("no weights at all: left to vLLM", [], "auto", None, None),
            ("another loader's format: left to vLLM", ["model.safetensors"], "gguf", None, None),
            ("bitsandbytes", ["model.safetensors"], "bitsandbytes", None, None),
        ]
        for what, weights, load_format, indexed, want in rows:
            with self.subTest(what):
                files = config + weights
                patterns = self.module.weight_patterns(files, load_format, indexed)
                if want is None:
                    self.assertIsNone(patterns)
                else:
                    self.assertEqual(kept(files, patterns, self.module.IGNORE), want)

    def test_config_files(self) -> None:
        files = ["config.json", "tokenizer.model", "chat_template.jinja", "merges.txt",
                 "model.safetensors", "pytorch_model.bin", "consolidated.00.pth", "model.gguf",
                 "original/params.json", "assets/logo.png", "odd[name].json"]
        self.assertEqual(kept(files, self.module.config_files(files), []),
                         ["config.json", "tokenizer.model", "chat_template.jinja", "merges.txt",
                          "odd[name].json"])

    def run_main(self, online: bool, cached: bool, load_format: str = "auto") -> tuple[int, str, list]:
        calls = []

        def list_repo_files(repo, revision=None):
            if not online:
                raise OSError("Hub unreachable")
            return ["config.json", "model.safetensors"]

        def snapshot_download(repo, **kwargs):
            calls.append(kwargs)
            if kwargs.get("local_files_only") and not cached:
                raise FileNotFoundError("not in the cache")
            return "/cache/snapshot"

        err = io.StringIO()
        with mock.patch.object(self.module, "list_repo_files", list_repo_files), \
                mock.patch.object(self.module, "snapshot_download", snapshot_download), \
                mock.patch.object(sys, "argv", ["download_model.py", MODEL, "", "", load_format]), \
                redirect_stderr(err):
            rc = self.module.main()
        return rc, err.getvalue(), calls

    def test_online(self) -> None:
        rc, _, calls = self.run_main(online=True, cached=False)
        self.assertEqual(rc, 0)
        (call,) = calls
        self.assertEqual(call["allow_patterns"], ["*.safetensors", "config.json"])
        self.assertEqual(call["ignore_patterns"], ["original/**/*"])

    def test_another_loaders_format_still_gets_the_config(self) -> None:
        rc, err, calls = self.run_main(online=True, cached=False, load_format="GGUF")
        self.assertEqual((rc, calls[0]["allow_patterns"]), (0, ["config.json"]))
        self.assertIn("--load-format gguf; vLLM downloads them", err)

    def test_hub_unreachable_serves_the_cached_snapshot(self) -> None:
        """HF_HUB_OFFLINE, an outage or no egress, after an earlier download."""
        rc, err, calls = self.run_main(online=False, cached=True)
        self.assertEqual(rc, 0)
        self.assertTrue(calls[-1]["local_files_only"])
        self.assertIn("serving the snapshot already in the cache", err)

    def test_hub_unreachable_and_nothing_cached_fails(self) -> None:
        rc, err, _ = self.run_main(online=False, cached=False)
        self.assertEqual(rc, 1)
        self.assertIn("OSError: Hub unreachable", err)


class PostStart(unittest.TestCase):
    """post_start.sh only adds the inference scrape jobs where vLLM serves."""

    text = (INFERENCE / "post_start.sh").read_text()

    def test_scrape_jobs_need_the_head_metrics_and_a_model(self) -> None:
        gate = re.search(r'^if \[\[ (.*) \]\]; then\n    exit 0\nfi$', self.text, re.M)
        self.assertIsNotNone(gate, "the head/metrics/model gate is gone")
        for cond in ('"${NODE_RANK:-}" != "0"', '"${RAY_CLUSTER_METRICS:-1}" == "0"', '-z "${MODEL_REPO:-}"'):
            self.assertIn(cond, gate.group(1))
        self.assertLess(gate.start(), self.text.index("job_name: vllm"))


if __name__ == "__main__":
    unittest.main()
