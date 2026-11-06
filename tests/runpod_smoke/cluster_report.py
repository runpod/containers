"""Per-cluster report card: one row per check, one column per node.

The run log is a few hundred lines per cluster and says everything, but not
at a glance. The card is filled in as the checks run (`mark`) and printed
under SUMMARY, so "what was tested, on what, and where did it stop" is one
table, not a scroll back through the log.

Every check the attempt is going to run is declared up front, so a check that
was never reached reads `not run` instead of silently missing from the table.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import config

OK = "ok"
FAIL = "FAIL"
NOT_RUN = "not run"
NA = "-"

# Row key -> (label, head_only). Declared in run order.
_BASE_ROWS = (
    ("ssh", "SSH ready", False),
    ("rank", "hostname / rank", False),
    ("cuda", "CUDA / torch", False),
    ("jupyter", "Jupyter via proxy", False),
    ("monitoring", "monitoring services", False),
    ("scrape", "Prometheus scrapes all nodes", True),
    ("grafana", "Grafana via proxy :{port}", True),
)


class ClusterReport:
    def __init__(self, image: str, gpu_id: str, node_count: int, gpus_per_node: int):
        self.image = image
        self.gpu_id = gpu_id
        self.node_count = node_count
        self.gpus_per_node = gpus_per_node
        self.cluster_id = ""
        self.cluster_type = ""
        self.data_center = ""
        self.verdict = ""
        self.detail = ""
        self.started = time.time()
        self.finished: Optional[float] = None
        self.hostnames = [f"node-{i}" for i in range(node_count)]
        self._rows: list[tuple[str, str, bool]] = [
            (key, label.format(port=config.GRAFANA_PORT), head_only)
            for key, label, head_only in _BASE_ROWS
        ]
        self._cells: dict[tuple[str, str], str] = {}

    # -- declaring and filling -------------------------------------------

    def add_rows(self, rows: list[tuple[str, str, bool]]) -> None:
        """Append rows (key, label, head_only) the attempt will also run."""
        known = {key for key, _, _ in self._rows}
        self._rows.extend(r for r in rows if r[0] not in known)

    def mark(self, key: str, hostname: str, status: str, note: str = "") -> None:
        """Record a result. A FAIL is never overwritten by a later ok."""
        if self._cells.get((key, hostname), "").startswith(FAIL):
            return
        self._cells[(key, hostname)] = f"{status} {note}".strip()

    def finish(self, verdict: str, detail: str) -> None:
        self.verdict, self.detail = verdict, detail
        self.finished = time.time()

    # -- rendering --------------------------------------------------------

    def _cell(self, key: str, head_only: bool, idx: int) -> str:
        if head_only and idx != 0:
            return NA
        return self._cells.get((key, self.hostnames[idx]), NOT_RUN)

    def _headline(self) -> str:
        elapsed = int((self.finished or time.time()) - self.started)
        parts = [
            f"cluster {self.cluster_id or '?'}",
            self.cluster_type or "?",
            f"{self.node_count} nodes x {self.gpus_per_node}x {self.gpu_id}",
        ]
        if self.data_center:
            parts.append(self.data_center)
        parts.append(f"{elapsed // 60}m{elapsed % 60:02d}s")
        return "  |  ".join(parts)

    def _table(self) -> tuple[list[str], list[list[str]]]:
        head = ["check", *(
            f"{h} (head)" if i == 0 else h for i, h in enumerate(self.hostnames)
        )]
        body = [
            [label, *(self._cell(key, head_only, i) for i in range(self.node_count))]
            for key, label, head_only in self._rows
        ]
        return head, body

    def render_text(self) -> list[str]:
        head, body = self._table()
        widths = [max(len(r[c]) for r in [head, *body]) for c in range(len(head))]

        def fmt(row: list[str]) -> str:
            cells = (cell.ljust(widths[c]) for c, cell in enumerate(row))
            return "  ".join(cells).rstrip()

        verdict = self.verdict or "?"
        lines = [f"{verdict}  {self.image}", f"  {self._headline()}", ""]
        lines.append("  " + fmt(head))
        lines.append("  " + "  ".join("-" * w for w in widths))
        lines.extend("  " + fmt(row) for row in body)
        if self.detail:
            lines += ["", f"  stopped at: {self.detail}"]
        return lines


# Reports of every attempt that created a cluster, for SUMMARY.
REPORTS: list[ClusterReport] = []
_REPORTS_LOCK = threading.Lock()
_current = threading.local()


def begin(report: ClusterReport) -> None:
    _current.report = report


def current() -> Optional[ClusterReport]:
    return getattr(_current, "report", None)


def mark(key: str, hostname: str, status: str, note: str = "") -> None:
    """mark() on the attempt in progress; a no-op outside one."""
    report = current()
    if report is not None:
        report.mark(key, hostname, status, note)


def end(verdict: str, detail: str) -> Optional[ClusterReport]:
    """Close the attempt; kept for SUMMARY only if a cluster was created."""
    report = current()
    _current.report = None
    if report is None or not report.cluster_id:
        return None
    report.finish(verdict, detail)
    with _REPORTS_LOCK:
        REPORTS.append(report)
    return report
