"""Durable local state with two recovery copies; never silently reset corruption."""

import json
import os
from pathlib import Path


def load_state(path, default=None):
    path = Path(path)
    found = False
    for candidate in (
        path,
        path.with_suffix(path.suffix + ".bak"),
        path.with_suffix(path.suffix + ".bak2"),
    ):
        if not candidate.exists():
            continue
        found = True
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("State must be an object")
            return value
        except (OSError, ValueError):
            continue
    if found:
        raise ValueError(
            "Discord state and its recovery copies are unreadable. Restore a saved sync-state.json before publishing."
        )
    return dict(default or {})


def save_state(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                raise ValueError()
        except (OSError, ValueError):
            pass
        else:
            backup = path.with_suffix(path.suffix + ".bak")
            if backup.exists():
                backup.replace(path.with_suffix(path.suffix + ".bak2"))
            backup.write_bytes(path.read_bytes())
    temporary.replace(path)
