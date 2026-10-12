from fight_importer import import_fight
from fight_scraper import get_fights_from_event
from fight_round_stats_importer import (
    import_fight_round_stats,
)
from import_one_completed_fight import (
    scrape_parent_event,
)
from uploader import import_event


# We already confirmed this is a completed fight.
# The script uses it to locate its parent event.
SEED_FIGHT_URL = (
    "http://ufcstats.com/fight-details/"
    "3146e5a47a922976"
)


if __name__ == "__main__":

    event = scrape_parent_event(
        SEED_FIGHT_URL
    )

    print("\nCompleted event:\n")
    print(event)

    event_result = import_event(
        event,
        dry_run=False,
    )

    print(
        "\nEvent result:",
        event_result,
    )

    fights = get_fights_from_event(
        event["url"]
    )

    if not fights:
        raise RuntimeError(
            "No fights found for the event."
        )

    imported_fights = 0
    updated_fights = 0
    failed_fights = 0

    stats_imported = 0
    stats_failed = 0
    total_stat_rows = 0

    print(
        f"\nProcessing {len(fights)} "
        "completed fights...\n"
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
            fight_result = import_fight(
                event["url"],
                fight,
                dry_run=False,
            )

            if (
                fight_result["status"]
                == "imported"
            ):
                imported_fights += 1

            elif (
                fight_result["status"]
                == "updated"
            ):
                updated_fights += 1

        except Exception as error:
            failed_fights += 1

            print(
                "FIGHT IMPORT FAILED:",
                error,
            )

            # Stats need a valid fight mapping,
            # so move to the next matchup.
            continue

        try:
            stats_result = import_fight_round_stats(
                fight["fight_url"],
                dry_run=False,
            )

            stats_imported += 1
            total_stat_rows += int(
                stats_result["round_rows"]
            )

        except Exception as error:
            stats_failed += 1

            print(
                "STATS IMPORT FAILED:",
                error,
            )

    print("\n" + "=" * 50)
    print("COMPLETED EVENT IMPORT FINISHED")
    print(f"Fights imported: {imported_fights}")
    print(f"Fights updated:  {updated_fights}")
    print(f"Fights failed:   {failed_fights}")
    print(f"Stats imported:  {stats_imported}")
    print(f"Stats failed:    {stats_failed}")
    print(f"Stat rows processed: {total_stat_rows}")
    print("=" * 50)
    print(
    f"Compact round rows processed: "
    f"{total_stat_rows}"
    )