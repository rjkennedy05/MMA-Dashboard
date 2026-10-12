"""Windows wakes regularly; this gate uses Central Time and catches up once."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def due_slot(job, now, hour, minute):
    local = now.astimezone(ZoneInfo("America/Chicago"))
    day = local.date()
    if job == "daily":
        if (local.hour, local.minute) < (hour, minute):
            return None
    else:
        day -= timedelta(days=(day.weekday() + 1) % 7)
        if local.date() == day and (local.hour, local.minute) < (hour, minute):
            day -= timedelta(days=7)
    return day.isoformat()


def should_run(state, job, now, hour, minute):
    slot = due_slot(job, now, hour, minute)
    retry = state.get("retry_at")
    if retry:
        try:
            if datetime.fromisoformat(retry) > now:
                return None
        except ValueError:
            pass
    return slot if slot and state.get("successful_slot") != slot else None


def sync_arguments(job, state, slot):
    if job != "daily":
        return []
    return ["--mode", "daily"] + (
        ["--skip-keyed-odds"] if state.get("attempted_slot") == slot else []
    )


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", choices=("daily", "history"), required=True)
    parser.add_argument("--time")
    args = parser.parse_args()
    hour, minute = map(
        int, (args.time or ("07:30" if args.job == "daily" else "11:00")).split(":")
    )
    if not (0 <= hour < 24 and 0 <= minute < 60):
        parser.error("Time must be HH:MM in Central Time.")
    path = ROOT / "api" / "sync" / "reports" / ("scheduled-" + args.job + ".json")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = datetime.now(timezone.utc)
    slot = should_run(state, args.job, now, hour, minute)
    if not slot:
        return 0
    script = (
        ROOT
        / "api"
        / "sync"
        / ("weekly_sync.py" if args.job == "daily" else "history_maintenance.py")
    )
    command = [sys.executable, str(script)] + sync_arguments(args.job, state, slot)
    state["attempted_slot"] = slot
    write_state(path, state)
    code = subprocess.run(command, cwd=ROOT, check=False).returncode
    finished = datetime.now(timezone.utc)
    if code == 0:
        state.update(successful_slot=slot, finished_at=finished.isoformat())
        state.pop("retry_at", None)
    else:
        state.update(
            retry_at=(finished + timedelta(minutes=30)).isoformat(), last_exit=code
        )
    write_state(path, state)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
