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


API_KEY = os.getenv(
    "THE_ODDS_API_KEY"
)

SPORT_KEY = (
    "mma_mixed_martial_arts"
)

BASE_URL = (
    "https://api.the-odds-api.com/v4"
)

REGIONS = resolve_regions(
    os.getenv("THE_ODDS_API_REGIONS")
)


if not API_KEY:
    raise ValueError(
        "THE_ODDS_API_KEY is missing "
        "from api/.env"
    )


def make_request(
    url: str,
    params: dict[str, Any],
) -> requests.Response:
    response = requests.get(
        url,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response


def get_events() -> list[dict[str, Any]]:
    """
    The events endpoint returns upcoming MMA
    matchups without odds and does not consume
    usage credits.
    """

    response = make_request(
        (
            f"{BASE_URL}/sports/"
            f"{SPORT_KEY}/events"
        ),
        {
            "apiKey": API_KEY,
            "dateFormat": "iso",
        },
    )

    return decode_utf8_json(response.content)


def get_moneyline_odds():
    """
    Query the configured bookmaker regions for broader
    small-promotion coverage.
    """

    response = make_request(
        (
            f"{BASE_URL}/sports/"
            f"{SPORT_KEY}/odds"
        ),
        {
            "apiKey": API_KEY,
            "regions": REGIONS,
            "markets": "h2h",
            "oddsFormat": "american",
            "dateFormat": "iso",
        },
    )

    return response


def print_event_summary(
    events: list[dict[str, Any]],
) -> None:
    print(
        f"\nUpcoming MMA events found: "
        f"{len(events)}\n"
    )

    for event in events[:30]:
        print(
            event.get("commence_time"),
            "|",
            event.get("home_team"),
            "vs",
            event.get("away_team"),
            "| ID:",
            event.get("id"),
        )


def print_odds_summary(
    fights: list[dict[str, Any]],
) -> None:
    print(
        f"\nFights with odds found: "
        f"{len(fights)}\n"
    )

    for fight in fights[:10]:
        print(
            "\n",
            fight.get("home_team"),
            "vs",
            fight.get("away_team"),
        )

        print(
            "Start:",
            fight.get("commence_time"),
        )

        bookmakers = fight.get(
            "bookmakers",
            []
        )

        print(
            "Bookmakers:",
            len(bookmakers),
        )

        for bookmaker in bookmakers[:3]:
            print(
                " ",
                bookmaker.get("title"),
            )

            for market in bookmaker.get(
                "markets",
                [],
            ):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get(
                    "outcomes",
                    [],
                ):
                    print(
                        "   ",
                        outcome.get("name"),
                        outcome.get("price"),
                    )


if __name__ == "__main__":
    events = get_events()

    print_event_summary(
        events
    )

    odds_response = get_moneyline_odds()

    odds = decode_utf8_json(
        odds_response.content
    )

    print_odds_summary(
        odds
    )

    print(
        "\nUsage information:"
    )

    print(
        "Last request cost:",
        odds_response.headers.get(
            "x-requests-last"
        ),
    )

    print(
        "Credits used:",
        odds_response.headers.get(
            "x-requests-used"
        ),
    )

    print(
        "Credits remaining:",
        odds_response.headers.get(
            "x-requests-remaining"
        ),
    )
