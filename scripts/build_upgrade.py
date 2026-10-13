"""Build the reviewable, atomic upgrade from its individual migrations."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = """-- Upgrade an existing v12 database; this is not a fresh-database schema.
-- Stop dashboard imports and the Discord runner; keep a database backup first.
begin;
do $$
declare t text;
begin
  foreach t in array array['events','fighters','fights','promotions','weight_classes','external_ids','data_sources','odds',
    'fight_research','event_research','bet_tickets','bet_legs','fighter_history_entries','fighter_history_coverage',
    'data_sync_runs','history_maintenance_runs','fight_stats','fight_round_stats'] loop
    if to_regclass('public.'||t) is null then raise exception 'Existing v12 schema is incomplete: missing %. Restore the working database schema before upgrading.',t; end if;
  end loop;
  if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='bet_tickets' and column_name='archived_at') then
    raise exception 'Apply the existing v12 migrations through 030 before this upgrade.';
  end if;
end $$;
"""


def build_upgrade():
    parts = [PREFLIGHT]
    for path in sorted(
        (ROOT / "supabase" / "migrations").glob("20261012003[1-5]_*.sql")
    ):
        parts.append(
            "-- "
            + path.name
            + "\n"
            + re.sub(r"(?m)^(?:begin|commit);[ \t]*$", "", path.read_text())
        )
    return "\n".join(parts + ["commit;\n"])


def build_resilient_upgrade():
    path = ROOT / "supabase/migrations/202610130036_isolate_import_reviews.sql"
    return "-- Additive update for an existing personal reliability database through 035.\n" + path.read_text()


if __name__ == "__main__":
    for filename, build in (("upgrade-personal-12.1.0.sql", build_upgrade),
                            ("upgrade-personal-resilience.sql", build_resilient_upgrade)):
        target = ROOT / "supabase" / filename
        if "--check" in sys.argv:
            if target.read_text() != build():
                raise SystemExit("Combined upgrade differs from its migrations; run scripts/build_upgrade.py.")
        else:
            target.write_text(build())
