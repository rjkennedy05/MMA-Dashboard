from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .response_utils import decode_utf8_json, resolve_regions
except ImportError:
    from response_utils import decode_utf8_json, resolve_regions


ENV_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        ".env",
    )
)

load_dotenv(ENV_PATH)


THE_ODDS_API_KEY = os.getenv(
    "THE_ODDS_API_KEY"
)

THE_ODDS_API_REGIONS = resolve_regions(
    os.getenv("THE_ODDS_API_REGIONS")
)


BASE_URL = (
    "https://api.the-odds-api.com/v4"
)

MMA_SPORT_KEY = (
    "mma_mixed_martial_arts"
)


def get_current_mma_moneylines(
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    api_key=os.getenv("THE_ODDS_API_KEY") or THE_ODDS_API_KEY
    if not api_key:raise ValueError("THE_ODDS_API_KEY is missing from api/.env")
    response = requests.get(
        (
            f"{BASE_URL}/sports/"
            f"{MMA_SPORT_KEY}/odds"
        ),
        params={
            "apiKey": api_key,
            "regions": THE_ODDS_API_REGIONS,
            "markets": "h2h",
            "oddsFormat": "american",
            "dateFormat": "iso",
        },
        timeout=30,
    )

    response.raise_for_status()

    usage = {
        "last": (
            response.headers.get(
                "x-requests-last"
            )
            or ""
        ),
        "used": (
            response.headers.get(
                "x-requests-used"
            )
            or ""
        ),
        "remaining": (
            response.headers.get(
                "x-requests-remaining"
            )
            or ""
        ),
        "regions": THE_ODDS_API_REGIONS,
    }

    return decode_utf8_json(response.content), usage
