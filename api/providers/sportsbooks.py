"""Shared provider book names; preserve regional keys where prices differ."""

import re

import json
from pathlib import Path

ALIASES = json.loads(
    Path(__file__).with_name("sportsbooks.json").read_text(encoding="utf-8")
)


def sportsbook_key(name, key=None):
    raw = str(key or name or "").strip().casefold()
    compact = re.sub(r"[^a-z0-9]", "", raw)
    return ALIASES.get(
        compact, raw if key else re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    )
