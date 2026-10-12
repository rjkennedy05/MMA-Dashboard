from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from matching import (
    matching_fighter_id,
    parse_height_inches,
    parse_reach_inches,
)
from uploader import supabase


UFCSTATS_SOURCE_ID = 1


def get_fighter_id_from_url(url):

    return url.rstrip("/").split("/")[-1]


def fighter_exists(external_id):

    response = (
        supabase
        .table("external_ids")
        .select(
            "internal_id"
        )
        .eq(
            "entity_type",
            "fighter"
        )
        .eq(
            "source_id",
            UFCSTATS_SOURCE_ID
        )
        .eq(
            "external_id",
            external_id
        )
        .execute()
    )

    if response.data:
        return response.data[0]["internal_id"]

    return None


def find_fighter_by_name(fighter_name):
    response = (
        supabase
        .table("fighters")
        .select("fighter_id, full_name")
        .execute()
    )
    return matching_fighter_id(response.data or [], fighter_name)


def attach_fighter_mapping(fighter_id, external_id, fighter_url):
    supabase.table("external_ids").insert(
        {
            "entity_type": "fighter",
            "internal_id": fighter_id,
            "source_id": UFCSTATS_SOURCE_ID,
            "external_id": external_id,
            "external_url": fighter_url,
        }
    ).execute()


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


def import_fighter(
    fighter_name,
    fighter_url
):

    external_id = get_fighter_id_from_url(
        fighter_url
    )


    existing = fighter_exists(
        external_id
    )


    if existing:

        print(
            "SKIP:",
            fighter_name
        )

        return existing


    profile = scrape_fighter(
        fighter_url
    )

    existing_name_id = find_fighter_by_name(
        fighter_name
    )

    if existing_name_id is not None:
        profile_update = {
            key: value
            for key, value in profile.items()
            if value is not None
        }
        if profile_update:
            supabase.table("fighters").update(
                profile_update
            ).eq(
                "fighter_id",
                existing_name_id,
            ).execute()
        attach_fighter_mapping(
            existing_name_id,
            external_id,
            fighter_url,
        )
        print("ATTACHED UFCSTATS:", fighter_name)
        return existing_name_id


    name_parts = fighter_name.split(
        " ",
        1
    )


    first_name = name_parts[0]

    last_name = (
        name_parts[1]
        if len(name_parts) > 1
        else None
    )


    fighter = {

        "first_name":
            first_name,

        "last_name":
            last_name,

        "full_name":
            fighter_name,

        "nickname":
            profile.get(
                "nickname"
            ),

        "height_inches":
            profile.get(
                "height_inches"
            ),

        "reach_inches":
            profile.get(
                "reach_inches"
            ),

        "stance":
            profile.get(
                "stance"
            ),

        "status":
            "active"
    }


    inserted = (
        supabase
        .table("fighters")
        .insert(
            fighter
        )
        .execute()
    )


    fighter_id = (
        inserted
        .data[0]["fighter_id"]
    )


    attach_fighter_mapping(
        fighter_id,
        external_id,
        fighter_url,
    )


    print(
        "IMPORTED:",
        fighter_name
    )


    return fighter_id
