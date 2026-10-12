from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path(__file__).with_name("manifest.json")


@lru_cache(maxsize=1)
def provider_manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    active = payload.get("active_promotions")
    archived = payload.get("archived_promotions")
    aliases = payload.get("aliases")
    if not isinstance(active, list) or not isinstance(archived, list) or not isinstance(aliases, dict):
        raise RuntimeError("The MMA provider manifest is invalid.")
    if set(active).intersection(archived):
        raise RuntimeError("A promotion cannot be both active and archived.")
    return payload


def normalized_promotion(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def promotion_key(value: Any) -> str | None:
    normalized = normalized_promotion(value)
    if not normalized:
        return None
    if "contender series" in normalized:
        return "dwcs"
    for key, candidates in provider_manifest()["aliases"].items():
        for candidate in candidates:
            alias = normalized_promotion(candidate)
            if normalized == alias or normalized.startswith(alias + " "):
                return key
    return None


def active_promotions() -> tuple[str, ...]:
    return tuple(provider_manifest()["active_promotions"])


def archived_promotions() -> tuple[str, ...]:
    return tuple(provider_manifest()["archived_promotions"])


def is_active_promotion(value: Any) -> bool:
    return promotion_key(value) in active_promotions()
