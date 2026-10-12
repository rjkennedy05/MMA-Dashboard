from scraper import get_events
from uploader import import_event


if __name__ == "__main__":

    events = get_events()

    if not events:
        raise RuntimeError(
            "No UFC events were returned by the scraper."
        )

    imported_count = 0
    skipped_count = 0
    failed_count = 0

    print(
        f"\nProcessing {len(events)} UFC events...\n"
    )

    for index, event in enumerate(
        events,
        start=1
    ):

        print(
            f"\n[{index}/{len(events)}] "
            f"{event['name']}"
        )

        try:

            result = import_event(
                event,
                dry_run=False
            )

            if result["status"] == "imported":
                imported_count += 1

            elif result["status"] == "skipped":
                skipped_count += 1

        except Exception as error:

            failed_count += 1

            print(
                f"FAILED: {event['name']}"
            )

            print(
                f"Error: {error}"
            )

    print("\n" + "=" * 40)

    print("UFC EVENT IMPORT COMPLETE")

    print(
        f"Imported: {imported_count}"
    )

    print(
        f"Skipped: {skipped_count}"
    )

    print(
        f"Failed: {failed_count}"
    )

    print("=" * 40)