"""Run isolated test groups so legacy module names cannot contaminate peers."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = []

    def run(name, command):
        command[0] = shutil.which(command[0]) or command[0]
        result = subprocess.run(
            command,
            shell=sys.platform == "win32" and command[0].endswith(".cmd"),
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        counts = re.findall(r"(?:Ran |# tests |ℹ tests )(\d+)", output)
        checks.append(
            {
                "name": name,
                "passed": result.returncode == 0,
                "tests": int(counts[-1]) if counts else 0,
                "exit_code": result.returncode,
            }
        )
        print(("PASS " if result.returncode == 0 else "FAIL ") + name, flush=True)
        if result.returncode:
            print(output[-12000:], flush=True)

    for folder in (
        "api/ufcstats",
        "api/providers/espn_mma",
        "api/providers/one_championship",
        "api/providers/lfa",
        "api/providers/bkfc",
        "api/providers/event_catalog",
        "api/providers/pfl_official",
        "api/providers/the_odds_api",
        "api/providers/api_sports_mma",
        "api/providers/fightodds",
        "api/providers/fighter_history",
        "discord-companion",
    ):
        run(
            folder,
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                folder,
                "-p",
                "test_*.py",
            ],
        )
    run(
        "sync and identity",
        [
            sys.executable,
            "-m",
            "unittest",
            "api.sync.test_incremental",
            "api.sync.test_retention",
            "api.sync.test_transient_retry",
            "api.sync.test_card_reconciliation",
            "api.sync.test_data_quality",
            "api.sync.test_freshness",
            "api.sync.test_readiness",
            "api.providers.test_fight_identity",
            "api.tests.test_reliability",
            "api.tests.test_release_contract",
            "scripts.test_scheduled_sync",
            "scripts.test_patch_bundle",
            "scripts.test_personal_update",
        ],
    )
    for name, command in [
        ("UI utilities", ["npm", "test"]),
        ("service contracts", ["npm", "run", "test:services"]),
        ("PostgreSQL", ["npm", "run", "test:database"]),
        ("lint", ["npm", "run", "lint"]),
        ("production build", ["npm", "run", "build"]),
    ]:
        run(name, command)
    run("daily CLI help", [sys.executable, "api/sync/weekly_sync.py", "--help"])
    run(
        "history CLI help",
        [sys.executable, "api/sync/history_maintenance.py", "--help"],
    )
    report = {
        "offline": True,
        "checks": checks,
        "tests": sum(c["tests"] for c in checks),
        "passed": all(c["passed"] for c in checks),
    }
    path = ROOT / "api" / "sync" / "reports" / "validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['tests']} tests; report: {path}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
