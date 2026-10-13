# Current personal reliability repairs

This checkpoint fixes the existing dashboard and companion. The dashboard stays
at 12.1.0, the companion contract stays at 6.3/provider core 1.1, and readiness
stays at schema 3. The database gains additive migration 036. Dependencies,
scheduled task names, installed folder paths and private settings are unchanged.

## Repairs and practical risks

| Existing problem | Repaired behavior | Risk or limit |
| --- | --- | --- |
| An ambiguous fighter or rejected fight stopped an entire card. | Each bout stages and commits its related records together. A failed bout rolls back its own changes, retains saved research/bets and receives a review flag. Other bouts commit. | A failed identity remains unresolved until source evidence or manual review settles it. Authentication, missing migrations and lost leases remain infrastructure failures. |
| Bethlehem's results used a new UUID for a fighter with two same-name database records. | A validated official BKFC fighter-page identity links the UUID to the existing BKFC record before global name matching. Contradictory established identities are flagged. | This relies on the established official page link, not a name merge. No historical fighters are merged or deleted. |
| Past unfinished cards fell outside the two-day daily window. | A full daily run retries up to six unresolved cards from the past 30 days through their saved source IDs. It skips resolved history and backs off repeated failures or source-complete omissions. | Older unresolved history still needs an explicit repair. No date or omission becomes a result. There are extra bounded public requests; this queue does not refetch paid odds. |
| Unresolved past bouts kept old channels in the current Discord week. | Past dated cards archive even with unresolved bouts. An asterisk and the existing dispute notice preserve access to those bouts; archived pending cards remain eligible for later updates. Live/postponed cards stay accessible. | Archive placement does not settle bets or confirm results. Preserve existing bot state to avoid duplicate channels/messages. |
| A bad quote could stop a matchup or leave one side looking freshly checked. | Invalid, incomplete or duplicate book pairs retain their prior prices. Other books continue. SQL commits each pair together and skips an older pair as a whole. | A source that cannot supply both participants still leaves an odds gap. Book/provider availability and quotas remain external limits. |
| A failed source blocked otherwise usable daily cards. | A completed final audit can publish good cards while unavailable sources and disputed saved cards receive warnings. If every card source fails or the snapshot/audit is unsafe, publication stops. | Publication with a warning means some saved information may be old. It does not certify complete source coverage. Scoped, dry-run, odds-only and maintenance runs still cannot replace a full daily handoff. |

Explicit source cancellations mark the affected bout cancelled. Absence from a
new card alone remains a review item. Stable participant sides, winners, accepted
ticket identities, research and source aliases stay protected.

## Evidence

The project runner exercises provider, real SDK/pagination, database/lease,
ticket, odds, Discord, installer, service and UI checks, plus lint, production
build and both CLI entry points. Run `python scripts/check_project.py`; its report
is `api/sync/reports/validation.json`. The database tests use isolated PostgreSQL.

The October 13 diagnostic and public source fixtures were also exercised against
the current import code: five DWCS results and eleven Bethlehem results updated
their existing bouts; all 13 official ONE results remained linked to their saved
bouts. There were no new fights/fighters or changed participant identities. Saved
research and bet-leg references remained identical. ONE fights 9507 and 9509,
absent from the source, remained unchanged and flagged. The three past cards
archived in the publisher simulation and disappeared from the weekly index.

This verification was offline against exported metadata and fetched public
responses. It does not apply repairs to the live database or update Windows
files. Discord REST access and the primary odds feed were checked separately.
API-Sports returned a Cloudflare challenge from this cloud machine; this does
not establish that the same request fails on the user's PC.

## Database prerequisite

Apply `supabase/upgrade-personal-resilience.sql` once to the existing database
already upgraded through 035, before running the repaired import source. It
checks its prerequisites, adds two service-only RPCs, and commits atomically.
It does not delete or merge rows, replace strict RPCs, rewrite bets or weaken
existing identity protections. Reapplying it is safe.

Use a schema/data backup of the real project before deployment. A source Git tag
or bundle protects source only. A working Supabase management token permits
checking the live schema and applying this migration; a REST service key alone
cannot execute the SQL upgrade. Credentials belong in secure environment
settings or the existing local `.env` files, never in chat or Git.

## Update the existing Windows folders without repeated ZIP transfers

These steps retain the current dashboard and bot folders. A separate Git checkout
holds the tested source. Install Git for Windows once if `git --version` fails.

1. Let refreshes finish and stop Discord 06. The database prerequisite above must
   be complete. In PowerShell, create the source checkout once:

   ```powershell
   git clone --branch personal-reliability-repairs https://github.com/rjkennedy05/MMA-Dashboard.git "$env:USERPROFILE\Desktop\MMA Tracker\MMA-Source"
   ```

2. Open that source folder in PowerShell and run the existing paired installer:

   ```powershell
   cd "$env:USERPROFILE\Desktop\MMA Tracker\MMA-Source"
   py -3.12 scripts/apply_personal_update.py --from-checkout
   ```

   It builds a checksum-verified patch from the committed Git source. It asks for
   the **existing working dashboard** and **existing working bot** folders. Press
   Enter when the displayed paths match those you use today. Both folders are
   checked before either is changed. Local source edits cause a stop instead of
   being overwritten. `.env`, bot settings, overrides and state stay in place.
   Recovery copies are made beside the working installations.

3. From your usual dashboard folder, run `npm run sync:now`, then start the
   dashboard and use the existing Discord 05/06 files. Dependencies and task
   paths did not change, so this source patch needs no reinstall or task repoint.

For a later approved repair, use the same source checkout:

```powershell
git pull --ff-only
py -3.12 scripts/apply_personal_update.py --from-checkout
```

The cloud workspace cannot edit the files on your PC. A Git branch becoming
available is not proof that the Windows installation received the source.

## Recovery

Stop workers before rollback. The installer prints each automatic recovery
folder; its `RESTORE-PATCH.bat` restores the prior source and checks for later
edits before overwriting anything. If you changed source afterward, preserve
those edits before restoring. Keep local bot state and `.env` intact.

The prior source remains at Git tag `personal-data-disputes-1`, commit
`7419162b3d64ab6b98e27ad23eff534c0fbafe32`, with an independent verified source
bundle/ZIP. Migration 036 can remain when rolling back: the prior strict RPCs
remain present. Do not delete new data or restore an old database backup without
accounting for bets/research added since that backup.

Historical duplicate candidates remain review findings. They are not silently
merged or deleted as part of this repair.
