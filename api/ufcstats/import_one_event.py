from scraper import get_events
from uploader import import_event


if __name__ == "__main__":

    events = get_events()

    if not events:
        raise RuntimeError(
            "No UFC events were returned by the scraper."
        )

    first_event = events[0]

    print("\nEvent selected for import:\n")

    print(first_event)

    result = import_event(
        first_event,
        dry_run=False
    )

    print("\nImport result:\n")

    print(result)