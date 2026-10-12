from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from page_reader import UfcstatsPageReader


TEST_FIGHT_URL = (
    "http://ufcstats.com/fight-details/"
    "3146e5a47a922976"
)


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def normalize_name(value: str) -> str:
    return clean_text(value).lower()


def get_external_id(url: str | None) -> str | None:
    if not url:
        return None

    return url.rstrip("/").split("/")[-1]


def get_cell_values(cell: Tag) -> list[str]:
    values = [
        clean_text(node.get_text(" ", strip=True))
        for node in cell.select("p")
    ]

    return [
        value
        for value in values
        if value
    ]


def parse_of_value(
    value: str,
) -> tuple[int, int] | None:
    """
    Convert:

        14 of 28

    into:

        (14, 28)
    """

    match = re.fullmatch(
        r"\s*(\d+)\s+of\s+(\d+)\s*",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return (
        int(match.group(1)),
        int(match.group(2)),
    )


def parse_integer(
    value: str,
) -> int | None:
    match = re.search(
        r"\d+",
        value,
    )

    return int(match.group()) if match else None


def parse_time_seconds(
    value: str,
) -> int | None:
    """
    Convert:

        3:12

    into:

        192
    """

    match = re.fullmatch(
        r"\s*(\d+):(\d{1,2})\s*",
        value,
    )

    if not match:
        return None

    minutes = int(match.group(1))
    seconds = int(match.group(2))

    return minutes * 60 + seconds


def extract_fighter_profiles(
    soup: BeautifulSoup,
) -> dict[str, dict[str, str | None]]:
    """
    Build a lookup from fighter name to UFCStats ID.
    """

    fighters: dict[
        str,
        dict[str, str | None],
    ] = {}

    for person in soup.select(
        ".b-fight-details__person"
    ):
        link = person.select_one(
            "a[href*='fighter-details']"
        )

        if not link:
            continue

        name = clean_text(
            link.get_text(" ", strip=True)
        )

        url = link.get("href")

        fighters[normalize_name(name)] = {
            "fighter_name": name,
            "fighter_url": url,
            "fighter_external_id":
                get_external_id(url),
        }

    return fighters


def add_single_stat(
    records: list[dict[str, Any]],
    fighter: dict[str, str | None],
    round_number: int,
    stat_name: str,
    value: int | None,
    unit: str = "count",
) -> None:
    if value is None:
        return

    records.append(
        {
            **fighter,
            "round_number": round_number,
            "stat_name": stat_name,
            "stat_value": value,
            "stat_unit": unit,
        }
    )


def add_landed_attempted_stats(
    records: list[dict[str, Any]],
    fighter: dict[str, str | None],
    round_number: int,
    base_name: str,
    value: str,
) -> None:
    parsed = parse_of_value(value)

    if not parsed:
        return

    landed, attempted = parsed

    add_single_stat(
        records,
        fighter,
        round_number,
        f"{base_name}_landed",
        landed,
    )

    add_single_stat(
        records,
        fighter,
        round_number,
        f"{base_name}_attempted",
        attempted,
    )


def get_fighter_identity(
    fighter_name: str,
    fighter_profiles: dict[
        str,
        dict[str, str | None],
    ],
) -> dict[str, str | None]:
    profile = fighter_profiles.get(
        normalize_name(fighter_name)
    )

    if profile:
        return profile

    return {
        "fighter_name": fighter_name,
        "fighter_url": None,
        "fighter_external_id": None,
    }


def parse_totals_table(
    table: Tag,
    fighter_profiles: dict[
        str,
        dict[str, str | None],
    ],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    rows = table.select("tbody tr")

    for round_number, row in enumerate(
        rows,
        start=1,
    ):
        cells = row.find_all(
            "td",
            recursive=False,
        )

        if len(cells) < 10:
            continue

        fighter_names = get_cell_values(
            cells[0]
        )

        knockdowns = get_cell_values(
            cells[1]
        )

        significant_strikes = get_cell_values(
            cells[2]
        )

        total_strikes = get_cell_values(
            cells[4]
        )

        takedowns = get_cell_values(
            cells[5]
        )

        submission_attempts = get_cell_values(
            cells[7]
        )

        reversals = get_cell_values(
            cells[8]
        )

        control_times = get_cell_values(
            cells[9]
        )

        for fighter_index, fighter_name in enumerate(
            fighter_names
        ):
            fighter = get_fighter_identity(
                fighter_name,
                fighter_profiles,
            )

            if fighter_index < len(knockdowns):
                add_single_stat(
                    records,
                    fighter,
                    round_number,
                    "knockdowns",
                    parse_integer(
                        knockdowns[
                            fighter_index
                        ]
                    ),
                )

            if fighter_index < len(
                significant_strikes
            ):
                add_landed_attempted_stats(
                    records,
                    fighter,
                    round_number,
                    "significant_strikes",
                    significant_strikes[
                        fighter_index
                    ],
                )

            if fighter_index < len(
                total_strikes
            ):
                add_landed_attempted_stats(
                    records,
                    fighter,
                    round_number,
                    "total_strikes",
                    total_strikes[
                        fighter_index
                    ],
                )

            if fighter_index < len(takedowns):
                add_landed_attempted_stats(
                    records,
                    fighter,
                    round_number,
                    "takedowns",
                    takedowns[
                        fighter_index
                    ],
                )

            if fighter_index < len(
                submission_attempts
            ):
                add_single_stat(
                    records,
                    fighter,
                    round_number,
                    "submission_attempts",
                    parse_integer(
                        submission_attempts[
                            fighter_index
                        ]
                    ),
                )

            if fighter_index < len(reversals):
                add_single_stat(
                    records,
                    fighter,
                    round_number,
                    "reversals",
                    parse_integer(
                        reversals[
                            fighter_index
                        ]
                    ),
                )

            if fighter_index < len(
                control_times
            ):
                add_single_stat(
                    records,
                    fighter,
                    round_number,
                    "control_time_seconds",
                    parse_time_seconds(
                        control_times[
                            fighter_index
                        ]
                    ),
                    unit="seconds",
                )

    return records


def parse_significant_strikes_table(
    table: Tag,
    fighter_profiles: dict[
        str,
        dict[str, str | None],
    ],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    rows = table.select("tbody tr")

    category_columns = {
        3: "significant_head_strikes",
        4: "significant_body_strikes",
        5: "significant_leg_strikes",
        6: "significant_distance_strikes",
        7: "significant_clinch_strikes",
        8: "significant_ground_strikes",
    }

    for round_number, row in enumerate(
        rows,
        start=1,
    ):
        cells = row.find_all(
            "td",
            recursive=False,
        )

        if len(cells) < 9:
            continue

        fighter_names = get_cell_values(
            cells[0]
        )

        for fighter_index, fighter_name in enumerate(
            fighter_names
        ):
            fighter = get_fighter_identity(
                fighter_name,
                fighter_profiles,
            )

            for column_index, stat_name in (
                category_columns.items()
            ):
                values = get_cell_values(
                    cells[column_index]
                )

                if fighter_index >= len(values):
                    continue

                add_landed_attempted_stats(
                    records,
                    fighter,
                    round_number,
                    stat_name,
                    values[fighter_index],
                )

    return records


class UfcstatsStatsUnavailableError(RuntimeError):
    pass


def parse_fight_stats(
    html: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    tables = soup.select(
        "table.b-fight-details__table"
    )

    if len(tables) < 2:
        raise UfcstatsStatsUnavailableError(
            "Expected two UFCStats statistics "
            f"tables, found {len(tables)}."
        )

    fighter_profiles = (
        extract_fighter_profiles(soup)
    )

    records = []

    records.extend(
        parse_totals_table(
            tables[0],
            fighter_profiles,
        )
    )

    records.extend(
        parse_significant_strikes_table(
            tables[1],
            fighter_profiles,
        )
    )

    return records


def scrape_fight_stats(
    fight_url: str,
) -> list[dict[str, Any]]:
    with UfcstatsPageReader(headless=True) as reader:
        html = reader.read(fight_url)
    return parse_fight_stats(html)


if __name__ == "__main__":
    stats = scrape_fight_stats(
        TEST_FIGHT_URL
    )

    print(
        f"\nNormalized stat records: "
        f"{len(stats)}\n"
    )

    for stat in stats[:30]:
        print(stat)
