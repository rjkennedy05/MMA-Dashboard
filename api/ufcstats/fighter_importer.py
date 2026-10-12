from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from matching import (
    matching_fighter_id,
    parse_height_inches,
    parse_reach_inches,
)
from uploader import supabase, get_ufcstats_source_id
from providers.persistence import find_identity, save_entity





def get_fighter_id_from_url(url):

    return url.rstrip("/").split("/")[-1]


def fighter_exists(external_id):
    mapping = find_identity(supabase, "fighter", get_ufcstats_source_id(), external_id)
    return int(mapping["internal_id"]) if mapping else None


def find_fighter_by_name(fighter_name):
    response = (
        supabase
        .table("fighters")
        .select("fighter_id, full_name")
        .execute()
    )
    return matching_fighter_id(response.data or [], fighter_name)


def attach_fighter_mapping(fighter_id, external_id, fighter_url):
    save_entity(supabase,"fighter",{},get_ufcstats_source_id(),external_id,fighter_id,fighter_url)


def parse_height(height):
    return parse_height_inches(height)


def parse_reach(reach):
    return parse_reach_inches(reach)


def scrape_fighter(url):

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page()

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(2000)

        soup = BeautifulSoup(
            page.content(),
            "html.parser"
        )

        browser.close()


    data = {}

    for item in soup.select(
        ".b-list__box-list-item"
    ):

        text = item.get_text(
            " ",
            strip=True
        )

        if "Nickname:" in text:
            nickname = (
                text.replace(
                    "Nickname:",
                    ""
                )
                .strip()
            )
            data["nickname"] = None if nickname == "--" else nickname

        if "Height:" in text:
            data["height_inches"] = parse_height(
                text.replace(
                    "Height:",
                    ""
                )
                .strip()
            )

        if "Reach:" in text:
            data["reach_inches"] = parse_reach(
                text.replace(
                    "Reach:",
                    ""
                )
                .strip()
            )

        if "Stance:" in text:
            stance = (
                text.replace(
                    "Stance:",
                    ""
                )
                .strip()
            )
            data["stance"] = None if stance == "--" else stance

        if "DOB:" in text:
            date_of_birth = (
                text.replace(
                    "DOB:",
                    ""
                )
                .strip()
            )
            data["date_of_birth"] = (
                None if date_of_birth == "--" else date_of_birth
            )


    return data


def import_fighter(fighter_name, fighter_url):
    external_id = get_fighter_id_from_url(fighter_url)
    existing = fighter_exists(external_id)
    if existing:
        return existing
    profile = scrape_fighter(fighter_url)
    existing_id = find_fighter_by_name(fighter_name)
    parts = fighter_name.split(" ", 1)
    payload = {key: value for key, value in profile.items() if value is not None}
    payload.update(first_name=parts[0], last_name=parts[1] if len(parts)>1 else None,
                   full_name=fighter_name, status="active")
    result = save_entity(supabase, "fighter", payload, get_ufcstats_source_id(), external_id, existing_id, fighter_url)
    return int(result["internal_id"])
