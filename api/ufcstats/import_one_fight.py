from fight_importer import import_fight
from fight_scraper import get_fights_from_event


EVENT_URL = (
    "http://ufcstats.com/event-details/"
    "1a50e734bb54861a"
)


if __name__ == "__main__":
    fights = get_fights_from_event(
        EVENT_URL
    )

    if not fights:
        raise RuntimeError(
            "No fights were found."
        )

    selected_fight = fights[0]

    print("\nSelected matchup:\n")
    print(selected_fight)

    result = import_fight(
        EVENT_URL,
        selected_fight,
        dry_run=False,
    )

    print("\nImport result:\n")
    print(result)