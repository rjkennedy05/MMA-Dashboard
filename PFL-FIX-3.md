# Dashboard 12.1.0 — PFL saved-fighter fix 3

The official PFL source returned Morocco's complete 11-fight card. The import
then refused to update saved fight #9540 because its incoming fighter IDs
differed from the IDs already attached to that fight.

The saved opponents supplied by the user were Shido Boris Esperanca (#5670)
and Peace Nguphane (#5673), with no current external source mappings. Accents
already normalize correctly in the importer. The previous SQL diagnostic can
miss accented duplicate names, so that output does not establish that there
are no duplicate fighter rows elsewhere in the database.

The previous importer could create a new fighter when a normalized name was
ambiguous, then select the older fight by its two opponent names. The identity
guard correctly rejected the new fighter IDs. This case now has a regression
test using the real PostgREST SDK, capped reads, and whole-card batch overlay.
The test reproduces the user's exact error with the previous importer and
passes with this update. The complete live database is not available here;
the precise reason the older importer picked different IDs remains unverified.

## What changed

Before global name lookup, the official PFL importer checks both opponent names
on the same saved event. When they identify one stored fighter pair, it attaches
the official source IDs to that pair and keeps the existing fighter records,
fight IDs, A/B sides, names, research, and ticket selections. Names use the
same accent, punctuation, spacing, and established first-name normalization
as the shared matchup finder. This is restricted to official PFL cards.

Conflicting established source mappings, multiple different stored fighter
pairs with the same names, and actual opponent replacements still require
review. No records are merged or deleted, and publication checks stay enabled.
Whole-card imports remain atomic: a conflict even on the final fight discards
all staged changes for that card.

## Windows installation

Use this small patch with dashboard 12.1.0 after PFL fix 2, which is the version
that produced the user's latest error.

1. Let any current refresh finish. In Discord's running 06 window, press Ctrl+C.
2. Download `MMA-Dashboard-12.1.0-PFL-fix-3.zip`.
3. In Downloads, right-click that ZIP and choose **Extract All**, then **Extract**.
4. Open the extracted folder and double-click **INSTALL-PATCH.bat**.
5. Check the displayed dashboard path and press Enter if it is the working
   folder. If asked for a path, open your working MMA-Dashboard folder in File
   Explorer, click its address bar, copy the address, and paste it into the
   installer window.
6. Wait for **Patch installed**. The installer checks the existing files and
   creates a backup in `MMA-patch-backups` alongside the dashboard folder.

No SQL, dependency install, Discord reinstall, or scheduled-task reinstall is
required. Local `.env` files remain in place. Installer backups cover changed
source files, not the live database. The backup folder includes
`RESTORE-PATCH.bat` to restore those source files if needed.

Then run this in PowerShell inside the working MMA-Dashboard folder:

```powershell
.\.venv\Scripts\python.exe api\sync\weekly_sync.py --mode daily --skip-keyed-odds
```

Read the new report, including the actual PFL errors:

```powershell
$report = Get-ChildItem .\api\sync\reports\sync_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$data = Get-Content $report.FullName -Raw | ConvertFrom-Json
[pscustomobject]@{
    pfl = $data.provider_runs.pfl_official
    errors = @($data.errors | Where-Object { $_.stage -eq "pfl_official" })
    warnings = @($data.warnings | Where-Object { $_.stage -eq "pfl_official" })
    catalog_issues = $data.catalog_issues
    publication_readiness = $data.publication_readiness
} | ConvertTo-Json -Depth 12
```

Expected for the reproduced case: PFL imports all 11 results, event_errors is
zero, and the Morocco source-gap warning clears. A conflicting saved source
mapping would still block that card and report both fighter IDs for review.
The ONE October 30 warning is outside the seven-day publication window on
October 12; its warning may remain after the PFL problem is resolved.

Run Discord 05 and then 06 once publication_readiness.ready is true. The user's
Windows installation, live database import, and Discord publication still need
confirmation from this local run. No live database writes or Discord messages
were performed from the cloud environment.
