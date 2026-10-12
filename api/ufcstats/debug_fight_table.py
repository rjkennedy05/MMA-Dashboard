from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


EVENT_URL = (
    "http://ufcstats.com/event-details/1a50e734bb54861a"
)


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True
    )

    page = browser.new_page()

    page.goto(
        EVENT_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    soup = BeautifulSoup(
        page.content(),
        "html.parser"
    )

    browser.close()


table = soup.find(
    "tbody"
)

rows = table.find_all(
    "tr"
)

print(
    "Rows found:",
    len(rows)
)


for row in rows[:3]:

    print("\n--- ROW HTML ---")

    print(
        row.prettify()[:2000]
    )


for link in row.find_all(
    "a",
    href=True
):
    print(
        "LINK:",
        link["href"]
    )
        
    
