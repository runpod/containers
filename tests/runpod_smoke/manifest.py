"""Manifest parser and value normalizers.

Avoids a PyYAML dependency since the format is predictable. See
../README.md for the schema reference.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


_TRUE_RE = re.compile(r"^(true|yes|on|1)$", re.IGNORECASE)
_FALSE_RE = re.compile(r"^(false|no|off|0)$", re.IGNORECASE)


def _normalize_bool(value: object) -> Optional[bool]:
    """Coerce a manifest scalar to bool. Returns None when the value isn't
    obviously truthy/falsy so callers can distinguish "absent" from "false"."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().strip('"').strip("'")
    if _TRUE_RE.match(s):
        return True
    if _FALSE_RE.match(s):
        return False
    return None


def _normalize_cuda_version(value: object) -> Optional[str]:
    """Coerce a manifest `min_cuda_version` value to the 'X.Y' string format
    that `runpodctl --min-cuda-version` expects.

    Accepts ints (`13` → '13.0'), floats (`12.8` → '12.8', `13.0` → '13.0'),
    and strings (with or without surrounding quotes). Returns None for
    empty/None inputs so callers can `value or fallback`-chain.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value}.0"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value)}.0"
        return f"{value:g}"
    return str(value).strip().strip('"').strip("'") or None


def _strip_quotes(s: str) -> tuple[str, bool]:
    """Strip a matching pair of surrounding quotes (single or double).
    Returns (value_without_quotes, was_quoted). Quoted values are not
    further coerced to numbers / booleans — the user asked for a string
    by quoting it."""
    if len(s) >= 2 and (
        (s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")
    ):
        return s[1:-1], True
    return s, False


def _coerce_scalar(raw: str) -> object:
    """Coerce an unquoted scalar value to bool / int / float, falling
    back to the raw string when nothing matches.

    Quoted values bypass this entirely (handled by `_strip_quotes`'s
    `was_quoted` flag in the caller) so `"13.0"` stays a string while
    bare `13.0` becomes a float.
    """
    if _TRUE_RE.match(raw):
        return True
    if _FALSE_RE.match(raw):
        return False
    try:
        return int(raw) if raw.lstrip("-").isdigit() else float(raw)
    except ValueError:
        return raw


def _classify_line(line: str, stripped: str) -> str:
    """Tag every non-blank, non-comment manifest line by its role.
    One of: 'group_header', 'list_key', 'scalar_kv', 'list_item', 'noop'."""
    if not line.startswith(" ") and line.endswith(":"):
        return "group_header"
    if line.startswith("    ") and line.endswith(":"):
        return "list_key"
    if stripped.startswith("- "):
        return "list_item"
    if (line.startswith("    ") and ":" in stripped
            and not stripped.endswith(":")):
        return "scalar_kv"
    return "noop"


def parse_manifest(path: Path) -> dict[str, dict]:
    """Parse a fixed-format manifest:

        groupname:
            images:
            - imagename
            instances:                  # explicit list (optional)
            - instance
            max_price_per_hour: 1.0     # OR budget filter (optional)
            min_vram_gb: 16             # extra filter (optional)
            manufacturer: Nvidia        # extra filter (optional)

    Supports both list values (`images:`, `instances:`) and scalar values
    (`max_price_per_hour: 1.0`). Scalars are auto-coerced to int/float
    when they look numeric, otherwise kept as strings. Surrounding
    quotes on scalars or list items are stripped and disable coercion.
    """
    data: dict[str, dict] = {}
    group: Optional[str] = None
    current_list: Optional[list[str]] = None

    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        kind = _classify_line(line, stripped)

        if kind == "group_header":
            group = line[:-1].strip()
            data[group] = {}
            current_list = None
        elif kind == "list_key":
            assert group is not None, f"List key {line!r} before any group"
            key = stripped[:-1]
            data[group][key] = []
            current_list = data[group][key]
        elif kind == "scalar_kv":
            assert group is not None, f"Scalar key {line!r} before any group"
            key, _, value = stripped.partition(":")
            value, quoted = _strip_quotes(value.strip())
            data[group][key.strip()] = value if quoted else _coerce_scalar(value)
            current_list = None
        elif kind == "list_item" and current_list is not None:
            item, _quoted = _strip_quotes(stripped[2:].strip())
            current_list.append(item)
    return data
