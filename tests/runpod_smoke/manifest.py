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
    (`max_price_per_hour: 1.0`). Scalars are auto-coerced to int/float when
    they look numeric, otherwise kept as strings.
    """
    data: dict[str, dict] = {}
    group: Optional[str] = None
    current_list: Optional[list[str]] = None

    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            group = line[:-1].strip()
            data[group] = {}
            current_list = None
        elif line.startswith("    ") and line.endswith(":"):
            assert group is not None, f"List key {line!r} before any group"
            key = stripped[:-1]
            data[group][key] = []
            current_list = data[group][key]
        elif (line.startswith("    ") and ":" in stripped
              and not stripped.startswith("- ")
              and not stripped.endswith(":")):
            # Scalar key: value (e.g. 'max_price_per_hour: 1.0').
            assert group is not None, f"Scalar key {line!r} before any group"
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Strip optional surrounding quotes so `min_cuda_version: "13.0"`
            # is parsed identically to `min_cuda_version: 13.0`. Numeric
            # and bool coercion are attempted only on unquoted values.
            quoted = len(value) >= 2 and (
                (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
            )
            if quoted:
                value = value[1:-1]
            parsed: object
            if quoted:
                parsed = value
            elif _TRUE_RE.match(value):
                parsed = True
            elif _FALSE_RE.match(value):
                parsed = False
            else:
                try:
                    parsed = (
                        int(value) if value.lstrip("-").isdigit() else float(value)
                    )
                except ValueError:
                    parsed = value
            data[group][key] = parsed
            current_list = None
        elif stripped.startswith("- ") and current_list is not None:
            item = stripped[2:].strip()
            # Strip optional surrounding quotes so users can write
            # `- "*Blackwell*"` (needed if they want the leading `*` to
            # avoid confusing a stricter YAML parser later). YAML treats
            # both forms identically — we do too.
            if len(item) >= 2 and (
                (item[0] == item[-1] == '"')
                or (item[0] == item[-1] == "'")
            ):
                item = item[1:-1]
            current_list.append(item)
    return data
