# MMA FightCenter — personal reliability 12.1.0

This release strengthens imports, saved bets, odds freshness, Discord
synchronization, and automatic jobs while keeping the existing dashboard layout.
It pairs with **Discord Companion 6.2 / provider core 1.1** and the existing
Supabase database upgraded through migration 035.

See [PERSONAL-RELIABILITY-12.1.md](PERSONAL-RELIABILITY-12.1.md) for the changes,
risks, installation sequence, verification, and recovery. The original v12/v6.1
sources and the 12.0.1 checkpoint remain preserved; no live database or Discord
messages were changed during this implementation.

MMA FightCenter is a desktop-first research and betting workspace for UFC,
DWCS, PFL, ONE, BKFC, and LFA. It combines current fight cards, fighter career
history, methods and opponent context, moneyline history, saved AI analysis,
research decisions, singles/parlays, grading, and ROI.

Version 12 is a reliability release. It does not add another dashboard panel.
It makes the existing dashboard and Discord companion use one promotion list,
one provider core, and one coordinated refresh sequence.

## Active and archived promotions

The shared provider manifest is `api/providers/manifest.json`.

- Active: UFC, DWCS, PFL, ONE, BKFC, and LFA.
- Archived: RIZIN.

RIZIN no longer appears in active navigation, coverage checks, refresh scopes,
scheduled network work, or new Discord event channels. Existing RIZIN events,
research, bets, parlay legs, grades, ROI, Discord messages, and pins are not
deleted. Historical RIZIN tickets remain available in Results & ROI.

## What v12 changes

- Checks the official UFC/DWCS and PFL event catalogs before detailed card
  enrichment, so a missing whole event is no longer silently invisible.
- Recognizes PFL Global, MENA, Africa, Europe, Champions Series, and generically
  titled regional events from PFL's official dated catalog.
- Repairs DWCS Season 10 Week 9, PFL MENA 11, and PFL Africa Morocco with the
  best official card/result information available at release time.
- Uses a two-day-past/21-day-future detailed daily window instead of broad
  historical work every morning.
- Always refreshes current fight week; unchanged distant cards are checked at
  most every three days unless a manual promotion refresh forces them.
- Moves fighter-history recovery and UFCStats enrichment to the Sunday
  maintenance task.
- Records a sync row as `running` before work begins and updates that same row
  at completion.
- Streams the current stage and elapsed time to Data Health during an in-app
  refresh.
- Reports missing events, empty cards, odds gaps, history gaps, and provider
  errors separately instead of treating a successful HTTP request as complete
  coverage.
- Merges the newer ESPN duplicate protections and BKFC XML/JSON result handling
  into the canonical dashboard provider library.
- Supplies that provider library to Discord v6; Discord no longer ships a
  second runtime copy of the parsers.

## Install or upgrade

See `UPGRADE-PHASE8-V12.md` for the v11.2-to-v12 sequence, then follow
`IMPLEMENTATION-01-BET-IDENTITY.md` for this patch. The two migrations are:

```text
supabase/migrations/202610050030_add_event_catalog_sources.sql
supabase/migrations/202610120031_protect_fight_identity.sql
```

An existing v12 installation needs only migration `031`; an existing v11.2
installation needs `030`, then `031`. A fresh database also requires the
original core schema, which is not included in these incremental migrations.
After restoring that schema, apply migrations in filename order.

Create/copy these private files locally; they are intentionally not packaged:

- `.env` — browser Supabase URL and publishable/anon key.
- `api/.env` — server-side Supabase credential plus optional odds keys.

Then install and start:

```powershell
npm install
python -m pip install -r api/requirements.txt
python -m playwright install chromium
npm run sync:now
npm run dev
```

No OpenAI API key is used. Full-card AI research remains the existing
copy-prompt/paste-response workflow.

## Refresh jobs

Install or repoint both Windows tasks from the active dashboard folder:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\install-daily-sync.ps1"
```

| Job | Default | Work performed |
| --- | --- | --- |
| MMA Dashboard Daily Sync | Daily, 7:30 AM local | Official catalog check, current cards, recent results, current odds, and final coverage audit |
| MMA Dashboard Weekly History Maintenance | Sunday, 11:00 AM local | Wider provider refresh, recent UFCStats enrichment, missing-history detection, API-Sports history fallback, then Sherdog fallback |

The dashboard does not need to be open for either task. The PC must be awake,
online, and able to run Python. The Sunday task does not replace the latest
daily status shown in Data Health.

Useful commands:

```powershell
npm run sync:now
npm run sync:ufc
npm run sync:pfl
npm run sync:one
npm run sync:lfa
npm run sync:bkfc
npm run sync:odds
npm run sync:history:maintenance
```

Promotion refreshes force that promotion's card check and also refresh current
odds. There is no RIZIN sync command.

## Data Health meanings

- **Automatic** — that detailed provider completed this refresh.
- **Catalog gap** — the official schedule could not be verified or an official
  event could not be reconciled safely.
- **Card gap** — the event exists but no active matchups are stored yet.
- **Odds gaps** — the card is inside the four-day expectation window and some
  active fights still lack tracked moneylines.
- **Review needed** — a provider completed only partially or failed.
- **Unchanged / Not run this refresh** — a scoped refresh intentionally did not
  run that promotion.

Odds are not flagged early: a card exactly five days away remains deferred.
Data Health lists uncovered matchups when lines should reasonably exist.

## Fighter history

FightCenter displays retained official event/fight results first and recovered
public history second. Sunday maintenance checks upcoming fighters and records
one of these honest states:

- complete public history;
- partial public history;
- confirmed professional debut;
- regional history unavailable;
- identity needs review.

Cancelled fights do not count as completed history. A provider failure cannot
erase previously confirmed bouts.

## Card research and betting

The card prompt uses the versioned response contract and stable fight keys.
Paste the completed response once at the bottom of the selected card; each
matchup receives its own saved narrative in Fight View. Parser compatibility
for earlier saved analyses remains.

Bet Center remains the only bet-entry path. Click one fighter for a single or
multiple fighters for a parlay, select the book, accept the imported price or
type a replacement price, enter stake, and save. Bet History supports edits,
deletion of erroneous tickets, grading, open exposure, and a current-period
reset that archives rather than deletes the earlier sample.

## Discord v6 contract

Discord v6 must be connected to this exact dashboard folder with
`04-CONNECT-DASHBOARD.bat`. It verifies provider-core version `1.0`, waits for
the current full daily dashboard run to reach success or partial, and only then
publishes the morning snapshot. Manual `/refreshfight` and `/refreshodds`
commands remain available for active event channels.

## Verification

```powershell
npm test
npm run lint
npm run build
npm run test:ufc
npm run test:pfl
npm run test:one
npm run test:lfa
npm run test:bkfc
npm run test:catalog
npm run test:odds
npm run test:history
npm run test:retention
npm run test:identity
npm run test:database
python -m compileall -q api
```

Credentials, installed dependencies, build output, reports, and local refresh
state are excluded from release packages.
