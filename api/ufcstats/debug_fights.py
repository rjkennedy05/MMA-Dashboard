from playwright.sync_api import sync_playwright


URL = "http://ufcstats.com/event-details/1a50e734bb54861a"


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True
    )

    page = browser.new_page()

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    links = page.locator("a").all()

    print("Total links:", len(links))

    for link in links[:30]:

        text = link.inner_text()

        href = link.get_attribute(
            "href"
        )

        if text.strip():

            print(
                text.strip(),
                href
            )

    browser.close()