"""Thin subprocess wrappers around the `runpodctl` binary.

Other modules go through these so we have one place to handle the
"binary not on PATH" / timeout cases consistently. JSON-mode parsing is
also centralized here.
"""

from __future__ import annotations

import json
import subprocess
import sys

from .log import log


def runpodctl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = ["runpodctl", *args]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        log("runpodctl not found in PATH. Install it first.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="", stderr="timeout"
        )


def runpodctl_json(*args: str, timeout: int = 60):
    """Invoke `runpodctl ... -o json` and parse stdout. Returns None on
    non-zero exit or malformed JSON (callers must handle the None case)."""
    proc = runpodctl(*args, "-o", "json", timeout=timeout)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
