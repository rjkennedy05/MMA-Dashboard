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
            "No fights were found for the event."
        )

    imported_count = 0
    updated_count = 0
    failed_count = 0

    print(
        f"\nProcessing {len(fights)} fights...\n"
    )

    for index, fight in enumerate(
        fights,
        start=1,
    ):
        matchup = (
            f"{fight['fighter_a_name']} vs "
            f"{fight['fighter_b_name']}"
        )

        print(
            f"\n[{index}/{len(fights)}] "
            f"{matchup}"
        )

        try:
            result = import_fight(
                EVENT_URL,
                fight,
                dry_run=False,
            )

            if result["status"] == "imported":
                imported_count += 1

            elif result["status"] == "updated":
                updated_count += 1

        except Exception as error:
            failed_count += 1

            print(
                f"FAILED: {matchup}"
            )
            print(
                f"Error: {error}"
            )

    print("\n" + "=" * 45)
    print("EVENT FIGHT IMPORT COMPLETE")
    print(f"Imported: {imported_count}")
    print(f"Updated:  {updated_count}")
    print(f"Failed:   {failed_count}")
    print("=" * 45)