# Personal tool update: post cards with data dispute markers

The user requested that an unresolved card difference should remain visible
without blocking the whole card or unrelated Discord updates. BKFC's official
Newark card currently lists 10 matchups. The two saved scheduled matchups absent
from that card are Irakli Ghvinjilia vs Jonathan Quiroz (#9580) and Jeff Lentz vs
Eduardo Peralta (#9581). This update preserves both for review.

## Resulting behavior

- Completed full daily refreshes can publish card differences as warnings.
  The event header, affected fight rows, and weekly index display an asterisk
  and a plain-language data dispute notice. Unaffected cards remain unmarked.
- Saved matchups keep their IDs, participants and status. Missing source rows
  are not treated as cancellations, and no fights, research, bets or tickets
  are deleted. A rejected individual card update can publish retained data with
  a review notice while the other cards update.
- The report and database run summary retain the issue codes and fight IDs.
  A fresh successful source check clears resolved markers and posts a resolution
  notice. Cached or unchecked cards keep their previous markers. Manual Discord
  card/odds updates keep a marker until the daily audit verifies resolution.
- Failed overall source discovery, unfinished/scoped refreshes, dry runs,
  incomplete audits, and inconsistent database reads still stop publication.
  The dashboard and companion use readiness schema 3 together; an older bot
  cannot silently publish the new warnings without displaying them.
- Card warning dates now use Central Time instead of slicing UTC timestamps.

## Install on Windows

This paired patch updates dashboard 12.1.0 with PFL fix 3 and companion 6.2 to
the new publishing behavior (companion 6.3). No SQL, npm/Python dependency
install, `.env` transfer, or new scheduled task is needed.

1. Let an active dashboard refresh finish. Stop any running Discord 05 or 06
   window with Ctrl+C.
2. Download `MMA-personal-data-disputes-1.zip`. In Downloads, right-click the
   ZIP, select **Extract All**, then **Extract**.
3. Open the extracted folder and double-click **INSTALL-UPDATE.bat**.
4. The installer displays the working **MMA-Dashboard** folder. Press Enter if
   it is correct. Next it displays the working **Discord bot** folder; press
   Enter if that is correct. If it asks for a path, open that working folder in
   File Explorer, click its address bar, copy the address, and paste it into the
   installer. The bot folder may still have its older Starter name; it is the
   folder containing the 05 and 06 scripts you normally run.
5. Wait for **Update installed in both projects**. Both projects are checked
   before either changes. Each project gets an automatic source backup under
   `MMA-patch-backups`; settings and Discord state remain in place. If copying
   the bot fails, the dashboard source is restored as well.

In PowerShell inside the working dashboard folder, run:

```powershell
.\.venv\Scripts\python.exe api\sync\weekly_sync.py --mode daily --skip-keyed-odds
```

Then show the new report:

```powershell
$report = Get-ChildItem .\api\sync\reports\sync_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $report.FullName -Raw | ConvertFrom-Json | Select-Object catalog_issues, publication_readiness | ConvertTo-Json -Depth 12
```

For the user's latest BKFC/ONE warnings, `ready` should be true and `disputes`
should retain the warnings. Run the usual Discord **05**, then **06**, from the
same working bot folder. Check the BKFC card and weekly index for asterisks.

## Recovery and validation limits

Each source backup includes `RESTORE-PATCH.bat`. To revert this paired update,
stop the bot and restore the latest dashboard and companion backups. Source
recovery does not undo live database imports or Discord posts; local settings
and Discord state stay in place. Restore the pair together, then run a matching
full daily refresh before restarting the older bot.

Project tests, simulated full publish cycles using the user's two BKFC matchup
IDs, cross-run snapshot checks, state preservation, and installer recovery are
verified in the cloud. The cloud environment has no live database credentials
or Discord connection settings. Native Windows launch and the actual server
posts need verification through the local steps above.
