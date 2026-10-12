# MMA FightCenter system blueprint and handoff

Updated October 6, 2026.

This is the shared source of truth for the coordinated releases:

- **Dashboard:** `MMA-Dashboard-phase8-reliability-v12.zip`
- **Discord companion:** `MMA-Discord-Companion-v6.1.zip`
- **Shared provider core:** version `1.0`

Before changing either project, inspect the latest package and latest available
state from both project conversations. Every future release must explain its
impact on the other project, local paths, environment files, Supabase schema,
Windows tasks, Discord state, dependencies, runner, and commands. State “none
required” explicitly where applicable.

## Product goal

Build one dependable personal MMA research system that improves on the useful
parts of Tapology: followed promotion schedules, current fight cards, fighter
history and result methods, opponent context, current/changed odds, independent
AI matchup write-ups, research decisions, and accepted-bet tracking.

Reliability takes priority over new panels. A provider request succeeding is
not proof that coverage is complete; whole-event, card, odds, and history gaps
must be detected and shown.

## Promotion scope

| State | Promotions |
| --- | --- |
| Active | UFC, DWCS, PFL, ONE, BKFC, LFA |
| Archived | RIZIN |

The canonical list lives in dashboard `api/providers/manifest.json`. Dashboard
sync/navigation/coverage and Discord setup/runtime validate the same manifest.

RIZIN retirement is non-destructive:

- no scheduled/manual RIZIN network reads;
- no active dashboard navigation/coverage requirement;
- no new Discord RIZIN promotion or event channels;
- existing events, fights, histories, research, odds, singles, parlay legs,
  grades, ROI, messages, discussion, and pins remain;
- historical RIZIN bets remain available in dashboard Results & ROI;
- old Discord RIZIN channels move to the archive without deleting messages;
- a manual RIZIN command returns a retired/preserved explanation before any
  network client is created.

## Ownership boundary

| Capability | Dashboard / Supabase | Discord companion |
| --- | --- | --- |
| Event catalog and stable identity | Authoritative | Reads after completed daily sync |
| Cards, cancellations, rebookings, results | Authoritative | Displays; manual direct read may temporarily be newer |
| Fighter profiles and career history | Authoritative | Does not build a second dossier database |
| Odds history | Authoritative | Manual fresh check and local movement baseline |
| Full-card AI analysis and research status | Authoritative | Publishes saved current-week analysis |
| Accepted singles and parlay tickets | Authoritative FightCenter | Copies details into pinned current-week My Bets blocks |
| Bet grading, live progress and ROI | Authoritative FightCenter | Does not publish or calculate these |
| Weekly channel structure/discussion | Supplies seed data | Authoritative presentation layer |
| Provider clients and parsers | Canonical shared core | Imports read-only clients/normalizers |

Discord direct observations never write to Supabase and never replace newer
confirmed data with an older dashboard snapshot.

## Dashboard v12 architecture

### Official catalog and detailed providers

- Official UFC/DWCS and PFL catalog pages are checked before detailed
  enrichment.
- PFL catalog parsing accepts its official regional/sub-brand names even when
  a card title omits the letters “PFL.”
- ESPN remains the structured UFC/DWCS/PFL card/result source when it covers an
  event.
- ONE uses ONE's official listing/event/status sources.
- LFA combines its official calendar with Sherdog card/result pages.
- BKFC uses official event pages and MMAReg XML/JSON results.
- The Odds API is primary keyed odds; API-Sports and public FightOdds are
  guarded fallbacks.

Migration `202610050030_add_event_catalog_sources.sql` registers the catalog
sources and repeat-safely repairs the omissions that triggered the pass:

- DWCS Season 10 Week 9 — five official matchups;
- PFL MENA 11 — eight official results;
- PFL Africa Morocco — seven officially announced matchups.

Detailed providers own subsequent changes/results. Safe card reconciliation
marks a removed scheduled matchup cancelled only after a complete successful
card import; research and bets remain attached.

### Refresh tiers

| Job | Default | Scope |
| --- | --- | --- |
| Fast daily | 7:30 AM local | Official catalogs, 2 days back/21 forward detailed cards, recent results, current odds, coverage audit |
| Weekly history maintenance | Sunday 11:00 AM local | Wider provider refresh, 7-day UFCStats enrichment, upcoming fighter-history audit and two fallbacks |
| Manual scoped refresh | User action | One promotion forced fresh plus current odds |
| Manual repair/backfill | Explicit command only | Broad/slow reconstruction |

The daily path always checks events from two days ago through seven days ahead.
Unchanged distant events are reused for up to three days unless a manual scoped
refresh forces them. History recovery and browser-based UFCStats enrichment no
longer block the morning card/odds run.

### Truthful health and progress

The sync creates one `data_sync_runs` row as `running`, streams named stages to
the local UI, records stage timings, then updates the same row to `success`,
`partial`, or `failed`. Data Health separates:

- missing official event/catalog unavailable;
- event exists but card empty;
- near-term odds empty or partial;
- fighter history unchecked, partial, unavailable, debut, or identity review;
- provider-level errors.

Odds are expected only inside four days; exactly five days remains deferred.

## Discord v6 architecture

Discord no longer packages a runtime `event_sources` fork. It connects to the
dashboard folder and validates provider-core version `1.0`, the six active
promotions, and RIZIN's archived state. Read-only provider modules are imported
from dashboard `api/providers`.

The 8:00 AM America/Chicago app job waits for today's full
`run_mode=daily`/`requested_scope=all` dashboard run. Success and partial are
publishable; failure or a 75-minute timeout preserves the previous complete
snapshot and retries after one hour. Scoped and maintenance runs cannot satisfy
the handshake. Manual `/refreshfight` and `/refreshodds` remain independent.

Setup v6 moves an existing `#rizin` channel to the archive by changing its
parent/topic only. The test suite verifies that user messages are unchanged and
no delete request occurs.

## Discord v6.1 — approved card and saved-bet bridge

The October 6 release implements the two approved changes. Dashboard v12,
provider-core 1.0, the six-promotion manifest, provider routing, Supabase schema,
and scheduled tasks are unchanged.

- A confirmed card/date/status/order change or published result now adds one
  fresh **Updated fight card** message containing every current matchup,
  confirmed result and explicitly cancelled row. The pinned card remains
  current. Unchanged refreshes do not add another lineup. Odds-only alerts
  retain their significant-swing format.
- Accepted FightCenter singles and complete parlay tickets now populate the
  pinned **My Bets** block in each matching current-week event channel. The
  existing guide's message ID and pin are reused; user messages and pins remain.
- Singles show selection, stake units, accepted odds and sportsbook. Parlays
  also show their label, accepted combined odds and every leg's accepted price.
  Cross-card tickets appear whole on each relevant current-week event, marked
  as one shared ticket with other-card event names. They do not create channels
  for out-of-week events and are not separate stakes per event.
- The bridge runs during the same existing 8:00 AM CT publication as promotion
  research, after the dashboard daily completion handshake, or through manual
  05. Saving a bet does not push immediately. Additions, edits and removals
  update that same block on the next publication; unchanged details stay quiet.
- Only positive-stake accepted bets are eligible. Archived/reset bets, drafts
  and research leans are excluded. Settlement fields, ROI and live leg progress
  are neither read for the bridge nor displayed. `/refreshfight` and
  `/refreshodds` preserve the saved bet block without database bet reads.
- Read-only access uses existing `fight_research`, `bet_tickets` and `bet_legs`
  relations and the dashboard server credential. Complete tickets are fetched
  by parent ID with all legs rather than filtering the ticket to one event.
  A unique dashboard bet owner is remembered before Discord publication;
  multiple owners require optional `MMA_DASHBOARD_BET_OWNER_ID` in the bot's
  local `.env`. Legacy shared single-bet rows remain compatible. A failed read,
  incomplete ticket or ambiguous owner retains the previous My Bets display
  while card/research publication continues. Archived blocks stay frozen.
- Large bet lists use complete continuation messages within Discord limits.
  Only recorded bot display pages are pruned, after a local backup. Further
  odds movement work is tabled; the existing command remains compatible.
- Code inspection confirms the manual Discord odds path checks **FightOdds
  first**, using the saved/overridden event odds URL or a uniquely matched
  upcoming event. It reads rendered sportsbook moneylines, matches both
  participants, and excludes opening/best/average/consensus columns.
- If FightOdds has no usable matching prices or cannot load, the bot uses
  **The Odds API** when `THE_ODDS_API_KEY` is present in the connected
  dashboard `api/.env`. Regions use `THE_ODDS_API_REGIONS`, defaulting to
  `us`; market is `h2h`. A partial usable FightOdds board does not trigger
  fallback gap filling. API-Sports is not in this manual command path.
- The dashboard's morning odds import still uses The Odds API as its primary
  provider and API-Sports/FightOdds as guarded fallbacks. Sharing provider
  clients does not mean these two entry points currently use the same order.
- The manual command saves an independent local baseline on its first read.
  Later checks compare each fighter/fight/sportsbook and alert at a cumulative
  five-percentage-point implied-probability change; it is not a five-percent
  relative price threshold. Prices are retained when a source is missing.
- Verification: 93 offline checks passed against the v6.1 runtime, including
  saved-bet filtering, read-only access, cross-card ticket completeness, owner
  binding, edit/removal handling, failed reads, long content and interruption
  recovery, plus complete-lineup, command, formatting, state recovery,
  archive, odds-alert and message-limit checks. Legacy fixture expectations
  were adjusted for six active promotion channels and full-card result posts.
  No signed-in Discord or user database was available for a live deployment.

### Upgrade an existing Discord v6.0 installation to v6.1

1. Stop the running 06 window with Ctrl+C (and 05 if active).
2. Copy this ZIP's extracted contents into the existing v6 bot folder.
3. Preserve `.env`, `setup-state.json`, `sync-state.json`,
   `bot-settings.json` and `event-overrides.json`.
4. Run `05-SYNC-THIS-WEEK.bat` once to populate saved-bet blocks.
5. Start `06-KEEP-UPDATING.bat` and wait for READY.

Background actions for this update:

- Dashboard v12/provider-core 1.0: no changes required.
- Environment credentials/dependencies/Discord permissions: no changes required
  for the existing personal dashboard connection. Only an explicit multiple
  bet-owner warning requires `MMA_DASHBOARD_BET_OWNER_ID` (the dashboard UUID,
  not the Discord user ID).
- Supabase migration, repair or backfill: none required.
- Both Windows scheduled tasks: no reinstall required if the dashboard stayed
  in the same folder.
- 05: run once for the first bet publication. 02/04/07: no rerun required for an
  existing working v6 connection.
- 04 must be rerun if the dashboard folder changed; moving the dashboard also
  requires reinstalling its two task paths.
- New command registration: none required; existing commands are registered
  by 06 at startup.
- Keep the PC awake and online with one 06 runner open.
- Earlier v5.2/v11.2 installations must complete the paired v12/v6 installation
  below before using this v6.1 companion.

If the dashboard folder moved, run 04 against the extracted folder containing
`api`, `src`, `package.json` and the working `api/.env`, not a `.zip` path. Open
PowerShell in that dashboard folder to repoint both tasks:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-daily-sync.ps1
```

## Installation and background actions

### Dashboard v12

1. Extract into a new folder.
2. Copy `.env` and `api/.env` from v11.2.
3. Run Supabase migration `202610050030_add_event_catalog_sources.sql`.
4. Run `npm install` and `python -m pip install -r api/requirements.txt`.
5. Run `python -m playwright install chromium` if the local browser dependency
   is not already installed.
6. Run `npm run sync:now`, then `npm run dev`.
7. Reinstall both Windows tasks from the v12 folder with
   `scripts/install-daily-sync.ps1`.

### Discord v6

1. Stop the old 06 runner.
2. Extract v6 and preserve `.env`, `setup-state.json`, `sync-state.json`,
   `bot-settings.json`, and `event-overrides.json`.
3. Run 04 and select the v12 folder, not its ZIP.
4. Run 02 once to verify six active channels/archive `#rizin`.
5. Run 07, then 05, then restart 06 and wait for READY.

Keep v11.2/v5.2 until one v12 daily refresh and one v6 publication complete.
Migration 030 is additive; rollback does not require undoing it, but task paths
and the Discord dashboard connection must point to whichever dashboard folder
is active.

## Verification completed in build workspace

- Dashboard: 63 frontend tests; 36 ESPN; 15 ONE; 9 LFA; 15 BKFC; 3 official
  catalog; 10 The Odds API; 6 fighter history; 20 sync/coverage/freshness;
  5 UFCStats; lint; production build; Python compilation.
- Discord v6.0 architecture: 116 tests passed with 12 retired legacy-RIZIN fixture tests skipped.
  Active coverage includes shared-provider loading, daily handshake, private
  setup, non-destructive RIZIN archival, command authorization, state recovery,
  direct result/odds preservation, weekly rollover, and Discord limits.
- Discord v6.1: 93 offline checks passed for saved bets, complete card updates
  and the compatible publisher/command/formatting/read-only regressions.

No real user credentials are included in either package. Live provider
availability and the user's Supabase migration must be confirmed on the first
local full refresh.

## Known limits and deliberate deferrals

- An official catalog can prove an event exists even when no safe detailed card
  source is available. That event is displayed with a Card gap instead of being
  silently absent.
- Public odds and regional fighter history can genuinely be unavailable. The
  system reports the gap; it does not invent prices, identities, or bouts.
- ChatGPT research remains copy/paste; no paid OpenAI API is used.
- No automatic articles, X/YouTube ingestion, cloud host or recurring live-event
  polling is included. Bet transfer is a scheduled snapshot only; further odds
  movement work, live leg progress and grading/ROI feeds are deferred.
- The computer must be awake and online; the Discord 06 runner must remain open.

## Future release checklist

Every delivery must state:

1. Dashboard and Discord versions inspected.
2. Shared provider-core version and promotion-manifest impact.
3. Folder/path changes and whether 04 must be rerun.
4. Environment/state files to preserve or edit.
5. Whether both Windows tasks must be reinstalled.
6. Whether Discord 06 must stop/restart and whether 07/command registration is
   needed.
7. Required migration, repair, or backfill.
8. Data/state preservation behavior.
9. Concrete verification for each changed system.
