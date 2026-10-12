from fight_round_stats_importer import (
    import_fight_round_stats,
)


FIGHT_URL = (
    "http://ufcstats.com/fight-details/"
    "3146e5a47a922976"
)


if __name__ == "__main__":
    result = import_fight_round_stats(
        FIGHT_URL,
        dry_run=False,
    )

    print("\nImport result:")
    print(result)