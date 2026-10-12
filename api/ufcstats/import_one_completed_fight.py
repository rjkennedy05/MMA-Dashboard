from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from fight_importer import import_fight
from fight_scraper import get_fights_from_event
from fight_stats_importer import import_fight_stats
from uploader import import_event


FIGHT_URL = (
    "http://ufcstats.com/fight-details/"
    "3146e5a47a922976"
)


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def scrape_parent_event(
    fight_url: str,
) -> dict[str, str | None]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        page = browser.new_page()

        page.goto(
            fight_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        fight_soup = BeautifulSoup(
            page.content(),
            "html.parser",
        )

        event_link = fight_soup.select_one(
            "a[href*='event-details']"
        )

        if not event_link:
            browser.close()

            raise RuntimeError(
                "Could not find the parent event."
            )

        event_url = event_link.get("href")

        page.goto(
            event_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        event_soup = BeautifulSoup(
            page.content(),
            "html.parser",
        )

        browser.close()

    title_node = event_soup.select_one(
        ".b-content__title-highlight"
    )

    event_name = clean_text(
        title_node.get_text(
            " ",
            strip=True,
        )
        if title_node
        else event_link.get_text(
            " ",
            strip=True,
        )
    )

    date_text = None
    location = None

    for item in event_soup.select(
        ".b-list__box-list-item"
    ):
        text = clean_text(
            item.get_text(" ", strip=True)
        )

        if text.startswith("Date:"):
            date_text = text.replace(
                "Date:",
                "",
                1,
            ).strip()

        elif text.startswith("Location:"):
            location = text.replace(
                "Location:",
                "",
                1,
            ).strip()

    event_date = None

    if date_text:
        event_date = datetime.strptime(
            date_text,
            "%B %d, %Y",
        ).date().isoformat()

    return {
        "name": event_name,
        "url": event_url,
        "event_date": event_date,
        "location": location,
        "event_status": "completed",
    }


def find_fight_on_event(
    event_url: str,
    fight_url: str,
):
    fights = get_fights_from_event(
        event_url
    )

    target_url = fight_url.rstrip("/")

    for fight in fights:
        current_url = (
            fight.get("fight_url")
            or ""
        ).rstrip("/")

        if current_url == target_url:
            return fight

    return None


if __name__ == "__main__":
    print(
        "\nFinding the completed fight's event..."
    )

    event = scrape_parent_event(
        FIGHT_URL
    )

    print(event)

    event_result = import_event(
        event,
        dry_run=False,
    )

    print(
        "\nEvent result:",
        event_result,
    )

    fight = find_fight_on_event(
        event["url"],
        FIGHT_URL,
    )

    if not fight:
        raise RuntimeError(
            "The completed fight was not found "
            "on its event page."
        )

    print(
        "\nImporting completed fight..."
    )

    fight_result = import_fight(
        event["url"],
        fight,
        dry_run=False,
    )

    print(
        "Fight result:",
        fight_result,
    )

    print(
        "\nImporting round-by-round stats..."
    )

    stats_result = import_fight_stats(
        FIGHT_URL,
        dry_run=False,
    )

    print(
        "\nStats result:",
        stats_result,
    )