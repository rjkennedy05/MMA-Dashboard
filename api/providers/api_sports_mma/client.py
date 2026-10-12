from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


API_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATHS = (API_ROOT / ".env", PROJECT_ROOT / ".env")

for env_path in ENV_PATHS:
    load_dotenv(env_path, override=False)


API_SPORTS_KEY_NAMES = (
    "API_SPORTS_MMA_KEY",
    "API_SPORTS_KEY",
    "APISPORTS_MMA_KEY",
    "APISPORTS_KEY",
    "API_MMA_KEY",
)

BASE_URL = "https://v1.mma.api-sports.io"


class ApiSportsMmaError(RuntimeError):
    pass


def resolve_api_sports_key() -> tuple[str | None, str | None]:
    """Return the configured key and its environment name without exposing it."""

    for variable_name in API_SPORTS_KEY_NAMES:
        value = (os.getenv(variable_name) or "").strip()
        if value:
            return value, variable_name
    return None, None


class ApiSportsMmaClient:
    def __init__(self, api_key: str | None = None, max_requests: int = 25) -> None:
        configured_key, configured_name = resolve_api_sports_key()
        self.api_key = api_key or configured_key
        self.key_environment = "explicit" if api_key else configured_name
        if not self.api_key:
            raise ApiSportsMmaError(
                "API-Sports MMA key was not found in api/.env or the project .env. "
                f"Accepted names: {', '.join(API_SPORTS_KEY_NAMES)}."
            )
        self.max_requests = max_requests
        self.request_count = 0
        self.daily_remaining: int | None = None
        import requests

        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})

    def get(self, endpoint: str, **params: Any) -> list[dict[str, Any]]:
        if self.request_count >= self.max_requests:
            raise ApiSportsMmaError(
                f"API-Sports request guard reached ({self.max_requests}); remaining work was deferred."
            )
        response = self.session.get(
            f"{BASE_URL}/{endpoint.lstrip('/')}", params=params, timeout=30
        )
        self.request_count += 1
        remaining = response.headers.get("x-ratelimit-requests-remaining")
        if remaining and remaining.isdigit():
            self.daily_remaining = int(remaining)
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            raise ApiSportsMmaError(f"API-Sports {endpoint} error: {errors}")
        rows = payload.get("response", []) if isinstance(payload, dict) else payload
        return rows if isinstance(rows, list) else []

    def odds_for_date(self, event_date: str) -> list[dict[str, Any]]:
        return self.get("odds", date=event_date)

    def find_fighter(self, name: str) -> dict[str, Any] | None:
        rows = self.get("fighters", search=name)
        from .normalizer import names_compatible, normalized_name

        compatible = [row for row in rows if names_compatible(fighter_name(row), name)]
        if len(compatible) == 1:
            return compatible[0]
        if len(compatible) > 1:
            return None

        canonical_query = normalized_name(name)
        simple_original = " ".join(str(name).casefold().split())
        if not canonical_query or canonical_query == simple_original:
            return None

        retry_rows = self.get("fighters", search=canonical_query)
        retry_compatible = [
            row for row in retry_rows if names_compatible(fighter_name(row), name)
        ]
        unique = {
            str(row.get("id") or fighter_name(row)): row for row in retry_compatible
        }
        return next(iter(unique.values())) if len(unique) == 1 else None

    def fighter_fights(self, fighter_id: int | str) -> list[dict[str, Any]]:
        return self.get("fights", fighter=fighter_id)


def fighter_name(row: dict[str, Any]) -> str:
    return str(
        row.get("name")
        or row.get("full_name")
        or " ".join(filter(None, (row.get("firstname"), row.get("lastname"))))
    ).strip()
