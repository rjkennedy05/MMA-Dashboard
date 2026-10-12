from __future__ import annotations

import json
from typing import Any


SUPPORTED_REGIONS = ("us", "uk", "eu", "au")
DEFAULT_REGIONS = SUPPORTED_REGIONS


def resolve_regions(configured_value: str | None) -> str:
    """Return a valid, de-duplicated Odds API region list."""
    requested = (
        configured_value.split(",")
        if configured_value
        else list(DEFAULT_REGIONS)
    )

    resolved: list[str] = []
    for region in requested:
        normalized = region.strip().lower()
        if normalized in SUPPORTED_REGIONS and normalized not in resolved:
            resolved.append(normalized)

    if not resolved:
        resolved = list(DEFAULT_REGIONS)

    return ",".join(resolved)


def decode_utf8_json(content: bytes) -> Any:
    """Decode provider JSON as UTF-8 instead of relying on charset guessing."""
    return json.loads(content.decode("utf-8"))
