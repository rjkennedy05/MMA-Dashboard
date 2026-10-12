from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "api"
UFCSTATS_ROOT = API_ROOT / "ufcstats"
sys.path.insert(0, str(UFCSTATS_ROOT))


def retention_cutoff(today: date, keep_days: int) -> date:
    if keep_days < 1:
        raise ValueError("Retention days must be at least 1.")
    return today - timedelta(days=keep_days)


def _first_row(response: Any) -> dict[str, Any]:
    rows = response.data or []
    return rows[0] if rows else {}


def preview_retention(
    supabase_client: Any,
    keep_days: int = 30,
) -> dict[str, Any]:
    retention_cutoff(date.today(), keep_days)
    response = supabase_client.rpc(
        "preview_mma_retention",
        {"keep_days": keep_days},
    ).execute()
    rows = response.data or []
    return {
        "status": "preview",
        "keep_days": keep_days,
        "events_eligible": len(rows),
        "fights_eligible": sum(int(row.get("fight_count") or 0) for row in rows),
        "events": rows,
    }


def apply_retention(
    supabase_client: Any,
    keep_days: int = 30,
) -> dict[str, Any]:
    retention_cutoff(date.today(), keep_days)
    response = supabase_client.rpc(
        "apply_mma_retention",
        {"keep_days": keep_days},
    ).execute()
    row = _first_row(response)
    return {
        "status": "completed",
        "keep_days": keep_days,
        "cutoff_date": row.get("cutoff_date"),
        "events_deleted": int(row.get("events_deleted") or 0),
        "fights_deleted": int(row.get("fights_deleted") or 0),
    }


def run_retention(
    supabase_client: Any,
    keep_days: int = 30,
    preview: bool = False,
    skipped: bool = False,
) -> dict[str, Any]:
    if skipped:
        return {"status": "skipped", "keep_days": keep_days}
    result = (
        preview_retention(supabase_client, keep_days)
        if preview
        else apply_retention(supabase_client, keep_days)
    )
    if result["status"] == "preview":
        print(
            "\nRetention preview — "
            f"{result['events_eligible']} events / "
            f"{result['fights_eligible']} fights eligible"
        )
    else:
        print(
            "\nRetention complete — "
            f"{result['events_deleted']} events / "
            f"{result['fights_deleted']} fights removed"
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply lean MMA result retention. Saved event research, "
            "fight research, and bet records are always protected."
        )
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--preview", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from uploader import supabase

    result = run_retention(
        supabase,
        keep_days=args.days,
        preview=args.preview,
    )
    if result["status"] == "preview":
        for event in result["events"]:
            print(
                f"  {event.get('event_date')} | "
                f"{event.get('promotion_name')} | "
                f"{event.get('event_name')} | "
                f"{event.get('fight_count')} fights"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
