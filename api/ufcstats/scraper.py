import os
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


EVENTS_URL = (
    "http://ufcstats.com/statistics/events/completed"
)


def clean_text(value):
    return " ".join(value.split())


def get_event_details(page, event):
    page.goto(
        event["url"],
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(1500)

    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    date_text = ""

    for item in soup.select(
        ".b-list__box-list-item"
    ):
        text = clean_text(
            item.get_text(" ", strip=True)
        )

        if text.startswith("Date:"):
            date_text = text.replace(
                "Date:",
                ""
            ).strip()
            break

    event_date = None

    if date_text:
        event_date = datetime.strptime(
            date_text,
            "%B %d, %Y"
        ).date().isoformat()

    location = None

    for item in soup.select(
        ".b-list__box-list-item"
    ):
        text = clean_text(
            item.get_text(" ", strip=True)
        )

        if text.startswith("Location:"):
            location = text.replace(
                "Location:",
                ""
            ).strip()
            break

    event_status = "unknown"

    if event_date:
        parsed_date = datetime.strptime(
            event_date,
            "%Y-%m-%d"
        ).date()

        event_status = (
            "upcoming"
            if parsed_date >= date.today()
            else "completed"
        )

    return {
        **event,
        "event_date": event_date,
        "location": location,
        "event_status": event_status
    }


def get_events(headless=None):
    if headless is None:
        headless = os.getenv(
            "UFCSTATS_HEADLESS",
            "true",
        ).lower() not in {"0", "false", "no"}

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=headless
        )

        page = browser.new_page()

        page.goto(
            EVENTS_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(5000)

        soup = BeautifulSoup(
            page.content(),
            "html.parser"
        )

        events = []
        seen_urls = set()

        for link in soup.find_all(
            "a",
            href=True
        ):

            href = link["href"].strip()

            if "event-details" not in href:
                continue

            name = clean_text(
                link.get_text(
                    " ",
                    strip=True
                )
            )

            if not name or href in seen_urls:
                continue

            seen_urls.add(href)

            events.append(
                {
                    "name": name,
                    "url": href
                }
            )

        detailed_events = []

        for index, event in enumerate(
            events,
            start=1
        ):

            print(
                f"Reading {index}/{len(events)}: "
                f"{event['name']}"
            )

            detailed_event = get_event_details(
                page,
                event
            )

            detailed_events.append(
                detailed_event
            )

        browser.close()

    return detailed_events


if __name__ == "__main__":

    events = get_events()

    print(
        f"\nImported {len(events)} event records\n"
    )

    for event in events[:5]:

        print(
            {
                "name": event["name"],
                "date": event["event_date"],
                "location": event["location"]
            }
        )
