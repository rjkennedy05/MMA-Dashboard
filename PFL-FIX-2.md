# Dashboard 12.1.0 — PFL card fix 2

The schedule patch succeeded. The remaining Morocco warning came from ESPN
not listing that event. PFL publishes its complete card in structured page
metadata and loads official results through its public `/smt/v2/` feed. This
update reads that source when an official calendar event is missing from ESPN.

## Windows installation

1. Stop Discord's 06 window with Ctrl+C and let any active refresh finish.
2. Download `MMA-Dashboard-12.1.0-PFL-fix-2.zip`.
3. In Downloads, right-click the ZIP, choose **Extract All**, and click **Extract**.
4. Open the extracted folder and double-click **INSTALL-PATCH.bat**.
5. The installer should find the dashboard path from your earlier command output.
   Read the displayed folder path and press Enter to use it. If it asks for a
   path, open the working MMA-Dashboard folder in File Explorer, click its
   address bar, copy the address, and paste it into the installer.
6. Wait for **Patch installed**. The installer makes a backup automatically
   and copies the replacement files into the correct locations. Keep the
   `MMA-patch-backups` folder it creates alongside your dashboard.

Your root/API `.env` files and Discord state stay in place. This cumulative
patch includes the first calendar fix. No new SQL, Python packages, npm install,
Discord reinstall, or scheduled-task reinstall is needed for this update.
The Python installation from the original setup must already have succeeded.

Then, in the existing dashboard PowerShell window, run:

```powershell
.\.venv\Scripts\python.exe api\sync\weekly_sync.py --mode daily --skip-keyed-odds
```

That refreshes all card sources using the project Python and skips paid odds
requests. Show the new report:

```powershell
$report = Get-ChildItem .\api\sync\reports\sync_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $report.FullName -Raw | ConvertFrom-Json | Select-Object catalog_issues, publication_readiness | ConvertTo-Json -Depth 12
```

When `publication_readiness.ready` is true, run bot 05 and then 06. If it stays
false, share that report output so the actual remaining issue can be diagnosed.
The ONE October 30 source warning is outside the blocking window on October 12.

## What is verified

- A live read of the official Morocco source returned 11 bouts: 10 wins and
  one no-contest. The adapter cross-checks every matchup against PFL's declared
  card before importing anything.
- Unknown statuses, mismatched dates, missing matchups, contradictory winners,
  wrong endpoints, and incomplete responses fail verification.
- Official cards use the existing PFL catalog source identity. They reuse the
  same whole-card transaction, stable fighter/fight identities, and bet/research
  protection as other imports. Midnight date placeholders do not become false
  kickoff times, and event dates alone cannot finalize results.
- ESPN continues to handle its existing listings. The fallback does not hide a
  failed ESPN card or disable Discord's publication checks.
- The installer checks checksums and supported source versions before changing
  files. It saves originals, restores already-written files on a copy failure,
  and provides RESTORE-PATCH.bat in the backup folder. Recovery stops if a file
  was edited after installing the patch.

The cloud checkout has no access to the live Supabase project or the Windows
computer. Live source reads, import/recovery tests, and package checks have
been performed; the user's complete refresh and Discord publishing remain
to be confirmed on the computer. Source backups do not include the live database.
