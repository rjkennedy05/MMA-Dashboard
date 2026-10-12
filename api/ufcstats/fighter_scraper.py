from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


def get_fighter_urls(event_url):

    fighters = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page()

        page.goto(
            event_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(3000)

        soup = BeautifulSoup(
            page.content(),
            "html.parser"
        )

        browser.close()


    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link["href"]

        if "fighter-details" not in href:
            continue

        name = (
            link.get_text(
                " ",
                strip=True
            )
        )

        if name:

            fighters[href] = name


    return [
        {
            "name": name,
            "url": url
        }
        for url, name in fighters.items()
    ]


if __name__ == "__main__":

    test_event = (
        "http://ufcstats.com/event-details/fccb0fee256b7b4d"
    )

    fighters = get_fighter_urls(
        test_event
    )

    print(
        f"Found {len(fighters)} fighters"
    )

    for fighter in fighters:
        print(fighter)