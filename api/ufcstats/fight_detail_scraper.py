from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from page_reader import UfcstatsPageReader


def clean_text(value: str | None) -> str:
    """Collapse extra whitespace into a single space."""
    return " ".join((value or "").split())


def get_external_id(url: str | None) -> str | None:
    """Extract the UFCStats identifier from a details URL."""
    if not url:
        return None

    return url.rstrip("/").split("/")[-1]


def parse_finish_time_seconds(value: str | None) -> int | None:
    """
    Convert a fight time such as 4:12 into total seconds.
    """
    if not value:
        return None

    match = re.fullmatch(r"(\d+):(\d{1,2})", value.strip())

    if not match:
        return None

    minutes = int(match.group(1))
    seconds = int(match.group(2))

    return minutes * 60 + seconds


def parse_integer(value: str | None) -> int | None:
    if not value:
        return None

    match = re.search(r"\d+", value)

    return int(match.group()) if match else None


def parse_scheduled_rounds(time_format: str | None) -> int | None:
    """
    Convert formats such as:
        3 Rnd (5-5)
        5 Rnd (5-5)
    into 3 or 5.
    """
    if not time_format:
        return None

    match = re.search(
        r"(\d+)\s*Rnd",
        time_format,
        flags=re.IGNORECASE,
    )

    return int(match.group(1)) if match else None


def normalize_result_type(method_code: str | None) -> str | None:
    """
    Convert UFCStats result codes into readable categories.
    """
    if not method_code:
        return None

    normalized = method_code.upper().strip()

    if "DEC" in normalized:
        return "Decision"

    if normalized in {"KO/TKO", "TKO", "KO"}:
        return "KO/TKO"

    if normalized in {"SUB", "SUBMISSION"}:
        return "Submission"

    if normalized == "DQ":
        return "Disqualification"

    if normalized in {"NC", "NO CONTEST"}:
        return "No Contest"

    return method_code.strip()


def extract_metadata(
    soup: BeautifulSoup,
) -> dict[str, str | None]:
    """
    Extract labeled UFCStats fields such as:
        METHOD
        ROUND
        TIME
        TIME FORMAT
        REFEREE
        DETAILS
    """
    metadata: dict[str, str | None] = {}

    for label_node in soup.select(
        ".b-fight-details__label"
    ):
        raw_label = clean_text(
            label_node.get_text(" ", strip=True)
        )

        label = raw_label.rstrip(":").lower()
        key = label.replace(" ", "_")

        parent = label_node.parent

        if parent is None:
            continue

        full_text = clean_text(
            parent.get_text(" ", strip=True)
        )

        value = full_text

        if raw_label and raw_label in value:
            value = value.replace(
                raw_label,
                "",
                1,
            ).strip()

        metadata[key] = value or None

    return metadata


def extract_fighters(
    soup: BeautifulSoup,
) -> list[dict[str, str | None]]:
    fighters: list[dict[str, str | None]] = []

    for person in soup.select(
        ".b-fight-details__person"
    ):
        link = person.select_one(
            "a[href*='fighter-details']"
        )

        if not link:
            continue

        status_node = person.select_one(
            ".b-fight-details__person-status"
        )

        fighter_url = link.get("href")

        fighters.append(
            {
                "name": clean_text(
                    link.get_text(" ", strip=True)
                ),
                "url": fighter_url,
                "external_id": get_external_id(
                    fighter_url
                ),
                "status": clean_text(
                    status_node.get_text(
                        " ",
                        strip=True,
                    )
                    if status_node
                    else None
                ).upper()
                or None,
            }
        )

    return fighters


def determine_fight_status(
    fighters: list[dict[str, str | None]],
    method_code: str | None,
) -> str:
    statuses = {
        fighter.get("status")
        for fighter in fighters
        if fighter.get("status")
    }

    normalized_method = (
        method_code.upper().strip()
        if method_code
        else None
    )

    if normalized_method in {"NC", "NO CONTEST"}:
        return "no_contest"

    if statuses == {"D"} or normalized_method in {
        "DRAW",
        "M-DEC",
    }:
        return "draw"

    if "W" in statuses:
        return "completed"

    # A future matchup generally has no winner or result data.
    return "scheduled"


def parse_fight_detail(
    html: str,
    fight_url: str,
) -> dict[str, Any]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    fighters = extract_fighters(soup)
    metadata = extract_metadata(soup)

    title_node = soup.select_one(
        ".b-fight-details__fight-title"
    )

    fight_title = clean_text(
        title_node.get_text(" ", strip=True)
        if title_node
        else None
    )

    method_code = metadata.get("method")
    method_details = metadata.get("details")

    winner = next(
        (
            fighter
            for fighter in fighters
            if fighter.get("status") == "W"
        ),
        None,
    )

    fight_status = determine_fight_status(
        fighters,
        method_code,
    )

    title_text = fight_title.lower()

    is_title_fight = (
        "title" in title_text
        or "championship" in title_text
    )

    return {
        "fight_url": fight_url,
        "external_id": get_external_id(
            fight_url
        ),
        "fight_title": fight_title or None,
        "fighters": fighters,
        "winner_url": (
            winner.get("url")
            if winner
            else None
        ),
        "winner_external_id": (
            winner.get("external_id")
            if winner
            else None
        ),
        "fight_status": fight_status,
        "result_type": normalize_result_type(
            method_code
        ),
        "method": (
            method_details
            or method_code
        ),
        "finish_round": parse_integer(
            metadata.get("round")
        ),
        "finish_time_seconds":
            parse_finish_time_seconds(
                metadata.get("time")
            ),
        "scheduled_rounds":
            parse_scheduled_rounds(
                metadata.get("time_format")
            ),
        "is_title_fight": is_title_fight,
        "raw_metadata": metadata,
    }


def scrape_fight_detail(
    fight_url: str,
) -> dict[str, Any]:
    with UfcstatsPageReader(headless=True) as reader:
        html = reader.read(fight_url)
    return parse_fight_detail(html, fight_url)


if __name__ == "__main__":
    TEST_FIGHT_URL = (
        "http://ufcstats.com/fight-details/"
        "68ae50dbf98dc15f"
    )

    result = scrape_fight_detail(
        TEST_FIGHT_URL
    )

    print("\nFight detail result:\n")

    for key, value in result.items():
        print(f"{key}: {value}")
