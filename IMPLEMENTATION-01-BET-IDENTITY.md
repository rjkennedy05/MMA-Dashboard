# Personal reliability patch 12.0.1 — stable fight identities

## Baseline saved before editing

- Dashboard: the exact uploaded `MMA-Dashboard-phase8-reliability-v12.zip`.
- Discord: the exact uploaded `MMA-Discord-Companion-v6.1.zip`.
- The starter v1 and older data-flow document are retained as references.
- Git baseline tag: `baseline/dashboard-v12-discord-v6.1`.
- Baseline commit: `c1f21d02e689a741b7c66c8375f4020290fd2049`.
- Verified copies, SHA-256 manifest, and complete Git bundle are stored in
  `/workspace/mma-baseline/2026-10-12/`. The original ZIPs and all extracted
  dashboard/companion files were compared byte-for-byte before committing.

This is a **source-code baseline**, not a backup of your live Supabase data,
credentials, Windows tasks, or Discord state. Those were not supplied or
changed. Download the baseline recovery ZIP for an independent copy. The Git
bundle includes the original README-only repository commit as well.

## Problem and resulting behavior

Saved single bets, parlay legs, research ratings, leans and AI picks refer to
`fighter_a` or `fighter_b` on a stored fight. Providers can reverse their
presentation order. Previously, an import could overwrite those positions and
silently change the meaning of the same saved selection.

Existing fights now retain their original fighter sides across ESPN UFC/DWCS,
ESPN PFL, ONE, LFA, BKFC and UFCStats imports. Results use fighter IDs, so the
winner remains the actual winning fighter. Normal card order, odds references
and result updates remain available. Newly inserted fights use their source's
initial order; subsequent imports preserve it.

An update that would replace the participants, move the fight to another
event, or follow a missing fight mapping raises an actionable review error.
The original fight, bet rows and mapping are retained instead of repurposing
the stored fight. Fighter/profile lookups may have occurred before this check.
Replacement bouts with a new provider identity can still be inserted normally.

Migration `031` adds the same invariant inside PostgreSQL. It also protects
against older importers and direct SQL/UPSERT operations: reverse ordering is
normalized to the stored sides, while participant/event/ID replacement is
refused atomically. Installing it does not rewrite any historical row.

## Scope and limitations

- This patch prevents future reinterpretation of existing stored fight sides.
  It cannot determine whether an earlier import already changed a historical
  bet's meaning. That requires source/ticket evidence and a separate review.
- Names alone are not sufficient to remap fighter IDs. Existing duplicate
  identities can produce a review error until reconciled deliberately.
- A source reusing a bout ID for a replacement/rebooking may require a new
  fight and an explicit provider mapping repair. Do not bypass the guard merely
  to make an import succeed.
- Concurrent-import coordination, stale-result preservation, additional single
  tickets, event reconciliation and Discord snapshot freshness are later steps.
- Discord code, bot permissions, provider-core version, credentials and task
  schedules are unchanged. The saved-bet bridge benefits from stable database
  sides without a data-format change.

## Verification

The patch includes 12 Python regression tests with per-provider cases covering
mapped updates, first-source attachment, repeated reversed imports, unchanged
bet/research rows, new fights, missing mappings, changed opponents, rebookings
and preserving mappings before a refused duplicate repair. UFCStats uses its
real update paths with an in-memory connection substituted for authentication.

Nine database checks execute migration `031` in PGlite, an isolated PostgreSQL
engine. They cover actual single/parlay selection joins, winner IDs, legacy
UPSERT, identity-change rejection, normal updates, repeat-safe migration and
transaction rollback and the optional migration rollback/reapply. No live
Supabase connection is used. PGlite 0.5.9 is a
locked development dependency and is not bundled into the application.

The existing 63 frontend tests and 80 provider/UFCStats tests also passed, along
with lint and the production build. These results do not establish live source
availability or that migration `031` has been applied to your Supabase project.

Reproduce from the dashboard directory, using Python with the existing API
requirements installed and Node 22.12 or newer:

```powershell
npm ci
npm run test:identity
npm run test:database
npm test
npm run lint
npm run build
```

## Upgrade an existing v12 installation

1. Keep a copy of the working dashboard and Discord folders, including their
   private configuration/state. Take a Supabase database backup before applying
   any migration. The supplied source baseline does not replace that backup.
2. Stop current imports and temporarily pause the two dashboard scheduled tasks.
   Stop the Discord 06 runner while files are being replaced.
3. Copy the patched dashboard release into the existing dashboard directory.
   The release excludes `.env`, `api/.env`, dependencies, build output and local
   state, so retain those private files. Discord remains in its existing folder;
   the bundled companion is an unchanged reference copy, not an upgrade.
4. In your existing Supabase project's SQL Editor, apply only:

   ```text
   supabase/migrations/202610120031_protect_fight_identity.sql
   ```

5. Run `npm ci` in the dashboard directory. Python production requirements are
   unchanged. Do not run old historical/seed migrations for this patch.
6. Run `npm run sync:now`. Verify Data Health, a saved single and a parlay leg.
   If an identity-review error appears, preserve the original records and review
   the mapping; do not delete a bet or disable the protection to clear it.
7. Re-enable the dashboard tasks, restart the dashboard as needed, and restart
   the existing Discord runner.

Keeping the same dashboard folder requires no task-path or bot connection
change. If the folder moves, follow the existing v12 instructions to reinstall
both task paths and reconnect Discord through 04. Preserve `setup-state.json`,
`sync-state.json`, `bot-settings.json` and `event-overrides.json`.

The cloud development instance has not applied this migration to your live
database or deployed the application. The release is prepared for review and
local installation.

## Rollback

Stop imports before restoring code. Restore the dashboard from the original
v12 ZIP into its existing folder, retaining private files. Leave the original
Discord v6.1 installation and its state in place. Run `npm ci` again.

The database guard is compatible with older code and can remain enabled during
a code rollback. For a complete rollback, the exact optional SQL is saved in:

```text
supabase/rollback/202610120031_protect_fight_identity.sql
```

Removing the guard restores the original unprotected behavior; it deletes no
fight, bet, research, or mapping row. Neither code nor migration rollback undoes
normal data imports performed after installation; restoring those requires the
separate live database backup.

To recover the baseline in a separate directory using the bundle:

```powershell
git clone MMA-baseline.bundle MMA-baseline-restored
git -C MMA-baseline-restored switch --detach baseline/dashboard-v12-discord-v6.1
```

The dashboard is at the restored root; the unchanged companion reference is in
`discord-companion`. Use the existing task checkout for normal development;
each cloud task is already isolated and does not require a Git worktree.
