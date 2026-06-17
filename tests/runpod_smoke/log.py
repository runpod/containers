"""Thread-tagged logging.

`log()` is the single place where everything emits to stdout. A small
lock prevents output from parallel workers being interleaved mid-line;
each pool thread gets a stable `W<N>` tag the first time it logs so the
output stays readable in MAX_PARALLEL > 1 runs.
"""

from __future__ import annotations

import threading
from datetime import datetime


_log_lock = threading.Lock()
_thread_local = threading.local()
_worker_id_lock = threading.Lock()
_next_worker_id = 0


def ensure_worker_tag() -> None:
    """Assign a stable W<N> tag to the current thread on first use.

    Reused for every job this pool thread runs, so all output from one
    pool worker stays under the same label even when len(jobs) > MAX_PARALLEL.
    """
    global _next_worker_id
    if getattr(_thread_local, "tag", None):
        return
    with _worker_id_lock:
        _next_worker_id += 1
        _thread_local.tag = f"W{_next_worker_id}"


def log(msg: str, indent: int = 0) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    tag = getattr(_thread_local, "tag", "")
    tag_part = f"[{tag}] " if tag else ""
    with _log_lock:
        print(f"[{ts}] {tag_part}{'  ' * indent}{msg}", flush=True)
