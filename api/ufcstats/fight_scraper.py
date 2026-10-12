from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


def get_fights_from_event(event_url):

    fights = []

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


    rows = soup.select(
        "tr.js-fight-details-click"
    )


    for order, row in enumerate(
        rows,
        start=1
    ):

        fight_url = row.get(
            "data-link"
        )

        fighters = row.select(
            "a[href*='fighter-details']"
        )

        if len(fighters) != 2:
            continue


        fighter_a = fighters[0]
        fighter_b = fighters[1]


        weight = row.select_one(
            "td:nth-of-type(7)"
        )


        fights.append(
            {
                "fight_url":
                    fight_url,

                "fighter_a_name":
                    fighter_a.text.strip(),

                "fighter_a_url":
                    fighter_a["href"],

                "fighter_b_name":
                    fighter_b.text.strip(),

                "fighter_b_url":
                    fighter_b["href"],

                "weight_class":
                    weight.text.strip()
                    if weight
                    else None,

                "fight_order":
                    order
            }
        )


    return fights



if __name__ == "__main__":

    EVENT_URL = (
        "http://ufcstats.com/event-details/1a50e734bb54861a"
    )


    fights = get_fights_from_event(
        EVENT_URL
    )


    print(
        f"Found {len(fights)} fights"
    )


    for fight in fights[:3]:

        print("\n")
        print(fight)