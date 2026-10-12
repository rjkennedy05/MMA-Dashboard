# Personal reliability 12.1.0

This is a source release for the existing personal dashboard and Discord bot.
The screen layout stays familiar. The original reliability release pairs with
Discord 6.2. The later [data dispute update](DATA-DISPUTES-1.md) pairs with Discord
6.3 and allows marked card differences to post. This installation requires
provider core 1.1, Node 24, Python 3.12, and database migrations through 035.

The original dashboard v12 and Discord v6.1 uploads remain preserved at Git tag
`baseline/dashboard-v12-discord-v6.1`. The first patch remains at
`personal-reliability-12.0.1`. Both have separate recovery archives and Git
bundles. These are source backups. They do not contain the live database,
credentials, Discord messages, or local bot/task state on your computer.

## What changed and why

| Area | Change | Risk / practical limit |
| --- | --- | --- |
| Imports | A card, fighters, bouts and source links commit together. Retries reuse identities. Old source IDs remain available as aliases. | Requires the new RPCs. A failed card keeps its prior data, which may be older. |
| Identity | Existing fighter sides, event assignments, accepted tickets and known outcomes remain protected. Conflicting source links stop for review. | Existing duplicates are preserved. Resolving them needs the actual records and proof of their identity. |
| Discovery | Empty ESPN feeds try alternate discovery. Official UFC/PFL entries are checked against detailed listings. Ambiguous catalog renames await detailed identity instead of creating another header. | Similar titles and genuine double headers can require another refresh or review. Public sites can change or omit data. |
| Completion | Missing bouts do not imply cancellation. Dates cannot finalize a card. Missing winners remain unresolved. A confirmed whole-event cancellation resolves remaining scheduled bouts and preserves known results. | Source cancellations can change automatic grading; saved book-confirmed grades still take precedence. |
| Coordination | Daily, UI, CLI and history imports share a renewable database lease. Expired workers cannot continue saving entities, odds, stats, history or completion status. | A long history job delays another import. Killed jobs recover after lease expiry and the next claim. |
| Handoff | Discord requires today's verified full daily card refresh, with an explicit readiness flag. Odds-only and maintenance runs cannot satisfy it. Optional odds/history gaps stay visible. | A card-source failure keeps the prior Discord snapshot. The scheduled gate retries unverified daily cards. |
| Bets | New singles have separate ticket records. Parlay creation, edits and period archives are transactional. Selected fighter IDs and edit revisions remain stable. | Historical singles remain readable on their legacy rows. A stale edit must reload. Reverting the UI hides new ticket singles until this release is restored. |
| Odds | Last observation is separate from last price change. Coverage requires recent prices for both fighters at one book. Older provider quotes cannot manufacture a new movement. Fallbacks target gaps. | History retains old quotes. Fresh coverage appears after a successful check. Provider availability and your key limits still apply. |
| Reads | Backend reads paginate past server caps; current odds matching uses a bounded event window. The browser batches card histories and requests representative first/latest/pre-fight quotes with real history counts. | The compact quote API requires migration 033. Historical quote times from older imports cannot be reconstructed automatically. |
| Discord | Newer observations replace stale overlays; identities reconcile when the dashboard catches up. Commands stay available during the daily wait. Research has one current display with retained revisions. Post intents recover lost responses. | Discord edits use several API requests; state and intents let a later run continue after interruption. Keep local state backups. |
| Jobs | Windows wakes regularly while Python uses America/Chicago. Slots catch up once, including DST changes. Automatic retry attempts use public/existing prices rather than repeating keyed odds calls. | The PC must be awake/online. The Windows task installer needs verification on the actual PC. Manual odds refreshes still use configured keys. |
| Privacy / setup | Owned research is private. Legacy unclaimed research is preserved and claimed on edit. A separate bot key can override the shared server key. Browser/importer project mismatches are rejected. Runtime dependencies are locked with hashes; CI runs offline checks. | Legacy unclaimed research remains available to authenticated users of this personal project. The server key itself is privileged; a scoped bot credential needs project configuration. |

## Install into the working project

1. Stop the bot and existing import jobs. Save the working folders, their `.env`
   files, bot state/configuration and a database backup from the actual Supabase
   project. The cloud source archives cannot back up a database they cannot access.
2. Apply `supabase/upgrade-personal-12.1.0.sql` to the **existing working project**.
   It checks prerequisites and runs migrations 031–035 in one transaction. If a
   prerequisite fails, stop and restore the missing existing schema before retrying.
   Do not deploy the new source until the upgrade commits successfully.
3. Overlay the dashboard and paired bot source while preserving local settings.
   Install with `npm ci` and Python 3.12:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --require-hashes -r api/requirements.txt
   ```

   Run the bot's `07-INSTALL-COMMANDS.bat` to install its locked runtime and browser
   support. Reconnect with 04 if the dashboard folder changed. Reinstall the two
   dashboard tasks using `scripts/install-daily-sync.ps1`; their gate now uses CT.
4. Run one full daily refresh. Review the displayed findings, then start the bot.
   Manual 05 also waits for a verified full daily run. Use `supabase/reliability-review.sql`
   for read-only findings about historical duplicates and ambiguous links.

No new GitHub repository, database project or Discord server is required.
Existing authentication/settings should point to the same existing project.

## Verification

`python scripts/check_project.py` runs isolated provider suites, import/lease
regressions, real PostgreSQL transaction and owner-policy checks, Discord tests,
real SDK service contracts, UI utilities, lint, build and CLI startup checks.
It writes `api/sync/reports/validation.json`. CI runs the same command with the
locked Node/Python runtime.

These checks use synthetic fixtures and an isolated PostgreSQL engine. They do
not verify the current live provider responses, real Supabase schema/authentication,
Discord permissions/posts, or native Windows Task Scheduler installation.
Live connection values were not available in this cloud workspace.

The repository still lacks the original core database DDL. The included upgrade
is for an existing v12 database. A fresh database or full disaster recovery needs
the schema/backup exported from the working project; the PostgreSQL test fixture
is not a production schema export.

## Recovery

Stop all workers before switching versions. Restore source from a verified tag,
bundle or recovery archive while keeping `.env` and local state/configuration.
The new columns/tables can remain: rolling back source does not require deleting
new data or weakening the identity/ownership guards.

The 12.0.1 UI does not display new single tickets stored in `bet_tickets`. Those
records remain intact and reappear with 12.1. Export/review any new bets before a
rollback. Restore a database backup only after accounting for records created
since it was taken. Do not run destructive historical merges as a rollback step.

For bot state, keep `sync-state.json`, `.bak`, `.bak2`, `setup-state.json`,
overrides/settings and `.env`. The 6.2 loader recovers a valid state copy and
stops if none can be read, rather than rebuilding duplicate channels/posts.

## Cloud development

GitHub read access was verified. Changes and release checkpoints are local;
the remote main still contains the starter commit. Future-task restoration has
not been verified. Retain the supplied release/recovery archives and do not reset
the current checkout to the starter repository.

Use the existing checkout and the verified Python environment. Reusable install
and startup instructions are saved in cloud environment settings for review.
No raw secrets belong in those scripts. Live requests need the actual project
settings, its network destination and the provider/Discord destinations.
