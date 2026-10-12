from __future__ import annotations

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright


# Completed five-round UFC fight with full statistics.
TEST_FIGHT_URL = (
    "http://ufcstats.com/fight-details/"
    "3146e5a47a922976"
)


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def get_cell_values(cell: Tag) -> list[str]:
    """
    UFCStats usually places each fighter's value
    in a separate <p> element inside the cell.
    """
    values = [
        clean_text(node.get_text(" ", strip=True))
        for node in cell.select("p")
    ]

    values = [
        value
        for value in values
        if value
    ]

    if values:
        return values

    fallback = clean_text(
        cell.get_text(" ", strip=True)
    )

    return [fallback] if fallback else []


def inspect_completed_fight(
    fight_url: str,
) -> None:
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

        html = page.content()

        browser.close()

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    print(
        "Page title:",
        clean_text(soup.title.string)
        if soup.title
        else None,
    )

    tables = soup.select(
        "table.b-fight-details__table"
    )

    print(
        f"\nStatistics tables found: "
        f"{len(tables)}"
    )

    for table_index, table in enumerate(
        tables,
        start=1,
    ):
        heading = table.find_previous(
            ["h2", "h3"]
        )

        heading_text = (
            clean_text(
                heading.get_text(
                    " ",
                    strip=True,
                )
            )
            if heading
            else None
        )

        headers = [
            clean_text(
                header.get_text(
                    " ",
                    strip=True,
                )
            )
            for header in table.select(
                "thead th"
            )
        ]

        rows = table.select(
            "tbody tr"
        )

        print("\n" + "=" * 60)
        print(f"TABLE {table_index}")
        print("Nearest heading:", heading_text)
        print("Headers:", headers)
        print("Rows:", len(rows))

        for row_index, row in enumerate(
            rows[:2],
            start=1,
        ):
            cells = row.find_all(
                "td",
                recursive=False,
            )

            print(
                f"\nRow {row_index}:"
            )

            for cell_index, cell in enumerate(
                cells,
                start=1,
            ):
                header = (
                    headers[cell_index - 1]
                    if cell_index <= len(headers)
                    else f"Column {cell_index}"
                )

                print(
                    f"  {header}: "
                    f"{get_cell_values(cell)}"
                )


if __name__ == "__main__":
    inspect_completed_fight(
        TEST_FIGHT_URL
    )