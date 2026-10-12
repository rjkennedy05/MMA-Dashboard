# Upgrade to MMA FightCenter Phase 8 v12

This is a coordinated dashboard-and-Discord reliability release. Install the
matching Discord v6 package after the dashboard is running.

## Preserved data

The upgrade does not delete events, fights, fighter history, research, odds,
single bets, parlays, grades, ROI, or archived betting periods. RIZIN is removed
from active tracking but its stored history remains readable.

## Dashboard upgrade

1. Extract the v12 ZIP into a new folder.
2. Copy `.env` and `api/.env` from the working v11.2 dashboard into the matching
   locations in v12.
3. In the Supabase SQL Editor, run:

   ```text
   supabase/migrations/202610050030_add_event_catalog_sources.sql
   ```

   This repeat-safe migration registers the two official schedule catalogs and
   repairs DWCS Season 10 Week 9, PFL MENA 11, and PFL Africa Morocco. It does
   not reset or delete any user data.

4. In PowerShell inside the folder containing `package.json`, run:

   ```powershell
   npm install
   python -m pip install -r api/requirements.txt
   python -m playwright install chromium
   npm run sync:now
   npm run dev
   ```

5. Open the address Vite prints, sign in, and open **Data Health**. Confirm the
   refresh is finished and that only UFC, DWCS, PFL, ONE, BKFC, and LFA appear.

6. Repoint both scheduled tasks to v12:

   ```powershell
   powershell -ExecutionPolicy Bypass -File ".\scripts\install-daily-sync.ps1"
   ```

7. Verify their working directories:

   ```powershell
   (Get-ScheduledTask -TaskName "MMA Dashboard Daily Sync").Actions |
     Format-List Execute, Arguments, WorkingDirectory

   (Get-ScheduledTask -TaskName "MMA Dashboard Weekly History Maintenance").Actions |
     Format-List Execute, Arguments, WorkingDirectory
   ```

Both `WorkingDirectory` values must point to the v12 folder. The daily arguments
must include `--mode daily`; the weekly action must use
`api\sync\history_maintenance.py`.

## Discord coordination

After installing the matching Discord v6 package:

1. Stop the old `06-KEEP-UPDATING.bat` window with Ctrl+C.
2. Preserve `.env`, `setup-state.json`, `sync-state.json`,
   `bot-settings.json`, and `event-overrides.json` from the working Discord
   folder.
3. Run `04-CONNECT-DASHBOARD.bat` and select the new v12 folder—not the ZIP.
4. Run `02-CREATE-CHANNELS.bat` once. It moves an existing `#rizin` promotion
   channel into the archive without deleting its messages or pins.
5. Run `07-INSTALL-COMMANDS.bat`, then `05-SYNC-THIS-WEEK.bat`.
6. Start `06-KEEP-UPDATING.bat` and wait for `READY`.

The 8:00 AM Discord job now waits for the current full dashboard daily refresh
to finish, so it cannot publish a half-updated morning snapshot.

## Rollback

Keep the v11.2 and Discord v5.2 folders until v12/v6 have completed one daily
refresh and one Discord sync. Returning to the old folders does not require a
database rollback. Migration `030` is additive and repeat-safe. If rolling
back, reinstall the dashboard scheduled tasks from the folder you choose and
reconnect Discord to that dashboard path.
