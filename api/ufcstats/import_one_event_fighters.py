from fighter_scraper import get_fighter_urls
from fighter_importer import import_fighter


EVENT_URL = (
    "http://ufcstats.com/event-details/1a50e734bb54861a"
)


if __name__ == "__main__":

    fighters = get_fighter_urls(
        EVENT_URL
    )

    print(
        f"Found {len(fighters)} fighters"
    )


    for fighter in fighters:

        import_fighter(
            fighter["name"],
            fighter["url"]
        )