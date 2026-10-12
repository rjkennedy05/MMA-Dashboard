# Dashboard 12.1.0 — schedule patch 1

This patch fixes the official UFC/PFL calendar errors from the October 12
refresh. It keeps the database schema and Discord Companion 6.2 contract.

## Install on the existing Windows dashboard

1. Stop the current refresh and Discord 06 runner. Make a copy of the existing
   `api/providers/event_catalog` folder for rollback.
2. Extract `MMA-Dashboard-12.1.0-schedule-fix-1.zip`. Merge its `api` folder into
   the existing **MMA-Dashboard** folder containing `package.json`, choosing
   Replace for matching files. The archive contains no `.env`, bot state,
   database migration, or dependency changes.
3. In PowerShell in that dashboard folder, finish the interrupted installation:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install --require-hashes -r api\requirements.txt
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```

   Run each command separately and wait for it to finish. A failed installation
   must be resolved before refreshing. `activate.bat` does not activate a
   PowerShell session; the commands below select the project Python directly.
4. Refresh every card source without another paid odds request:

   ```powershell
   .\.venv\Scripts\python.exe api\sync\weekly_sync.py --mode daily --skip-keyed-odds
   ```

5. Show the latest report's verification findings:

   ```powershell
   $report = Get-ChildItem .\api\sync\reports\sync_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   Get-Content $report.FullName -Raw | ConvertFrom-Json | Select-Object catalog_issues, publication_readiness | ConvertTo-Json -Depth 12
   ```

   `publication_readiness.ready` must be true before running bot 05 and then 06.
   Odds coverage gaps alone can leave the refresh PARTIAL while cards are ready.
6. To start the dashboard from PowerShell with its refresh buttons using the
   same Python environment:

   ```powershell
   $env:MMA_DASHBOARD_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
   npm run dev
   ```

No SQL upgrade or Discord reinstall is needed for this patch. Continue using
the existing database and local settings. The original 12.1.0 source archive
is preserved; rollback consists of restoring the copied catalog folder.

## What changed

- UFC main-card timestamps now provide the event date in Central Time. Headings
  such as “Buckley vs Malott” gain the official event label from their URL.
  Ticket-sale dates and neighboring event cards cannot supply missing dates.
- PFL month/day headings resolve their year from a declared URL year or the
  Upcoming/Past section. Weekdays must agree, and inferred dates remain within
  one year. Unidentified yearless archive cards stay unverified.
- The short official title “PFL Chicago 2” matches “PFL Chicago: Carmouche vs.
  Bishop 2” when the promotion/date and named prefix agree. Conflicting editions
  and multiple plausible stored events remain rejected.
- A recognized schedule with its next event outside the requested window is
  a quiet window, while unreadable pages and old archival metadata still fail.

## Verification and remaining coverage

Regression fixtures contain the actual official schedule markup fetched on
2026-10-12. The live read-only check confirms that the current UFC cards match
ESPN's detailed listings and that the PFL Chicago naming difference resolves.
The original publication checks remain in place.

The corrected PFL calendar also discovers **PFL Africa Morocco, 2026-10-10**.
ESPN's scoreboard and Core window list only Chicago for this date range, and
the official Morocco event page does not expose a fight card. A daily refresh
can therefore report `DETAIL_SOURCE_GAP` for Morocco and keep Discord paused.
That is a real coverage gap requiring a verified card source, not another
calendar parsing error. The patch does not claim that today's full database
refresh is publishable or synthesize missing fights/results.

Live database imports, the user's Windows execution, and Discord publishing
cannot be verified from the source-only cloud checkout. The patch includes
its validation report and SHA-256 manifest.
