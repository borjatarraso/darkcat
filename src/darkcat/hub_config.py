"""Persisted settings for the multi-protocol Chat hub.

The hub auto-refresh interval is the one knob users tweak often
(10s / 30s / 1m / 10m / 30m / 1h / custom). Keeping it in its own
tiny JSON file under ``~/.darkcat/hub.json`` avoids dragging the
crawler ``Config`` dataclass into runtime-persisted state — the rest
of darkcat treats ``Config`` as a process-scoped default bag.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


HUB_CONFIG_PATH = Path.home() / ".darkcat" / "hub.json"

DEFAULT_INTERVAL_SECONDS = 30

# Preset choices the UI surfaces. Tuples of (label, seconds). `off`
# disables auto-refresh entirely (manual `r` only).
INTERVAL_PRESETS: list[tuple[str, int]] = [
    ("10s", 10),
    ("30s", 30),
    ("1m", 60),
    ("10m", 600),
    ("30m", 1800),
    ("1h", 3600),
    ("off", 0),
]


def _interval_for_label(label: str) -> Optional[int]:
    for lbl, secs in INTERVAL_PRESETS:
        if lbl == label:
            return secs
    return None


def _label_for_interval(seconds: int) -> str:
    for lbl, secs in INTERVAL_PRESETS:
        if secs == seconds:
            return lbl
    if seconds <= 0:
        return "off"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def parse_interval(value: str | int) -> int:
    """Parse a human interval like ``30s`` / ``2m`` / ``1h`` / ``off``
    into seconds. Bare ints / digit strings are taken as seconds.

    Raises :class:`ValueError` on garbage. ``0`` / ``off`` means
    auto-refresh disabled."""
    if isinstance(value, int):
        return max(0, value)
    s = str(value).strip().lower()
    if not s or s in {"off", "0", "manual", "none"}:
        return 0
    preset = _interval_for_label(s)
    if preset is not None:
        return preset
    unit = s[-1]
    if unit.isdigit():
        return max(0, int(s))
    head = s[:-1]
    if not head.isdigit():
        raise ValueError(f"invalid interval {value!r}")
    n = int(head)
    if unit == "s":
        return n
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    raise ValueError(f"invalid interval unit {unit!r} in {value!r}")


def load() -> dict:
    """Load the hub-config JSON. Returns the default mapping when the
    file is missing or corrupt — never raises."""
    try:
        with HUB_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"refresh_interval_seconds": DEFAULT_INTERVAL_SECONDS}
    if not isinstance(data, dict):
        return {"refresh_interval_seconds": DEFAULT_INTERVAL_SECONDS}
    data.setdefault("refresh_interval_seconds", DEFAULT_INTERVAL_SECONDS)
    return data


def save(data: dict) -> None:
    """Persist ``data`` to ``~/.darkcat/hub.json`` (0600). Creates
    the parent directory if it doesn't exist."""
    HUB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HUB_CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, HUB_CONFIG_PATH)
    try:
        HUB_CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def get_interval() -> int:
    """Return the persisted refresh interval in seconds (>= 0)."""
    return int(load().get("refresh_interval_seconds", DEFAULT_INTERVAL_SECONDS))


def set_interval(seconds: int) -> int:
    """Persist a new refresh interval. Negative values are clamped to 0
    (manual-refresh only). Returns the value actually stored."""
    secs = max(0, int(seconds))
    data = load()
    data["refresh_interval_seconds"] = secs
    save(data)
    return secs


def interval_label(seconds: int) -> str:
    """Best-effort short label for a stored interval (UI helper)."""
    return _label_for_interval(int(seconds))


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "HUB_CONFIG_PATH",
    "INTERVAL_PRESETS",
    "get_interval",
    "interval_label",
    "load",
    "parse_interval",
    "save",
    "set_interval",
]
