# One-time PFL Morocco cleanup

These are manual maintenance scripts, not application migrations or setup
commands. The user authorized removing the remaining omitted fight #9541 after
the PFL fix 3 report showed all 11 official bouts imported with no errors.
Fight #9540's identity problem was resolved by that import and it stays intact.

Run `remove-pfl-morocco-9541.sql` in the MMA project's Supabase SQL Editor using
its default postgres role. Let any active refresh finish and stop Discord 06
first. The script also coordinates with the existing database import lock.

The script requires the reported PFL event and date, a scheduled target with
no confirmed result, and 11 completed official bouts with their PFL source
pointers. Any research row, bet leg, unknown linked data, or active import stops
it without deleting data. It removes only #9541 and its odds, statistics, and
fight-source mappings. Event and fighter records stay in place.

Before deleting anything, the transaction saves the complete removed rows in
`mma_recovery.fight_cleanups`. That schema and table deny access to public,
anon, and authenticated roles. Repeating a successful cleanup preserves the
original backup. `restore-pfl-morocco-9541.sql` restores the removed rows using
their original IDs; conflicts stop recovery without overwriting current data.

The cleanup and recovery passed PostgreSQL tests with the existing identity
and result protections enabled. They have not been executed against the user's
live database. The cloud environment has no credentials for that database.

After the successful cleanup, run this in PowerShell inside MMA-Dashboard:

```powershell
.\.venv\Scripts\python.exe api\sync\weekly_sync.py --mode daily --skip-keyed-odds
```

That refresh rebuilds the report and publication readiness from the cleaned
card. Existing report files and saved run summaries are historical and are not
rewritten by the cleanup. Once publication_readiness.ready is true, run Discord
05 and then 06. The ONE October 30 warning is outside the seven-day publication
window on October 12.
