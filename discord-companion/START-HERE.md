# MMA Discord Companion — version 6.1

Version 6.1 is the coordinated companion for **MMA FightCenter Phase 8 v12**.
Install the dashboard first. Discord now uses the dashboard's provider clients
and parsers instead of carrying a second copy that can drift out of date.

## Upgrade from v6.0

1. Stop the running 06 window with Ctrl+C (and 05 if active).
2. Copy this ZIP's extracted contents into your existing v6 bot folder.
3. Keep `.env`, `setup-state.json`, `sync-state.json`, `bot-settings.json`, and
   `event-overrides.json` when they exist.
4. Run `05-SYNC-THIS-WEEK.bat` once to publish your saved FightCenter bets.
5. Start `06-KEEP-UPDATING.bat` and wait for `READY`.

This update requires no dashboard changes, migration, dependency
installation, permission change, scheduled-task reinstall, or rerun of
02/04/07 for a working v6 connection. Existing commands register at startup.
If the dashboard moved, rerun 04 and reinstall its two Windows tasks from that
dashboard folder. Keep the computer awake and online with one 06 window open.

Card/date/status/order changes and published results now add one fresh full
lineup message. The pinned card stays current; unchanged checks stay quiet.
Saved singles and complete parlay tickets now fill the pinned My Bets block in
each matching current-week event channel during the same sync as research.

## Upgrade from v5.2

1. Stop `06-KEEP-UPDATING.bat` with Ctrl+C. Stop 05 too if it is running.
2. Extract this ZIP into a new Discord v6 folder.
3. Copy these files from the working v5.2 folder when they exist:

   - `.env`
   - `setup-state.json`
   - `sync-state.json`
   - `bot-settings.json`
   - `event-overrides.json`

4. Run `04-CONNECT-DASHBOARD.bat`. Select the extracted **dashboard v12
   folder containing `api`, `src`, and `package.json`**, not its ZIP.
5. Run `02-CREATE-CHANNELS.bat` once. It verifies the six-promotion layout and
   moves an existing `#rizin` channel into the archive. It does not delete the
   channel, its messages, or its pins.
6. Run `07-INSTALL-COMMANDS.bat`.
7. Run `05-SYNC-THIS-WEEK.bat` once.
8. Start `06-KEEP-UPDATING.bat` and leave that window open. Wait for `READY`.

No Discord token or Supabase credential should be pasted into chat. The
existing `.env` files remain local.

## Active promotions

Discord creates and updates current-week content for UFC, DWCS, PFL, ONE, BKFC,
and LFA. RIZIN is retired from new network requests and active channel creation.
An old RIZIN command returns a clear preservation message instead of contacting
a provider.

## Coordinated morning flow

The dashboard task starts at 7:30 AM local time. The Discord app job becomes
eligible at 8:00 AM America/Chicago, but it no longer assumes the dashboard is
finished. It checks today's full daily sync row and waits until that exact run
is `success` or `partial` before reading and publishing the snapshot.

- A partial dashboard run is published with a review note because successful
  providers have already saved their data.
- A failed run or a 75-minute timeout preserves the previous Discord snapshot
  and retries one hour later.
- Scoped/manual and weekly-maintenance runs do not satisfy the handshake.
- Manual event commands remain available while the dashboard is running.

## Event commands

| Command | Behavior |
| --- | --- |
| `/refreshfight` | Reads the selected active event's latest card/status/results through the shared dashboard provider core. |
| `/refreshodds` | Reads fresh FightOdds prices, with the configured The Odds API fallback when necessary, then posts only qualifying same-book movement. |

Both commands are owner-only, event-channel scoped, and protected by the
existing one-minute cooldown. Confirmation replies are private. A failed or
partial provider read keeps the last confirmed card, result, or price.

The first odds check establishes a quiet baseline. Later checks alert when the
cumulative same-book change reaches five implied-probability percentage points.
The normal card post does not become an odds board.

### Where manual odds come from

The bot opens the public FightOdds event page in a hidden browser, using the
saved event URL or a unique title/date match. It reads sportsbook moneylines
and safely matches both opponents to the card. Opening, best, average and
consensus columns are excluded. Props and totals are not included.

If FightOdds has no usable matching prices or cannot load, the bot tries The
Odds API using `THE_ODDS_API_KEY` from the connected dashboard's `api/.env`.
Regions use `THE_ODDS_API_REGIONS`, defaulting to `us`; the requested market is
`h2h`. Any usable FightOdds prices, including partial coverage, end that check
without calling the fallback to fill gaps. The reply reports source, coverage
and check time. A check does not write odds back to Supabase.

API-Sports is not used by this Discord command. The dashboard morning importer
has its own routing: The Odds API primary, then guarded API-Sports/FightOdds
fallbacks. Both applications still use the same dashboard provider core.

### What My Bets does

Save your accepted bets in FightCenter. The existing research sync copies
them into each matching current-week event channel's pinned **My Bets** block:

- Singles show your selection, stake in units, accepted odds and sportsbook.
- Parlays show the ticket label, total stake, accepted combined odds,
  sportsbook and every leg with its accepted price.
- A parlay spanning multiple cards is shown as one complete shared ticket on
  each relevant current-week card. Its other-card legs are labelled with their
  events; the display does not create extra event channels.

This uses the existing 8:00 AM CT publication after the dashboard daily run
finishes, or a manual `05-SYNC-THIS-WEEK.bat`. It is not an immediate push. Bet
additions, edits and removals update that same block on the next publication.
Unchanged bets do not produce new messages. Large lists use continuation
messages when Discord's limits require them; the first remains pinned.

Research leans, zero-stake drafts and archived/reset bets are excluded.
Settlements, results, live leg progress and ROI are not part of the block.
`/refreshfight` and `/refreshodds` preserve the last saved My Bets display.
Dashboard FightCenter remains the official bet record. Your own Discord notes
and pins remain available; archived event blocks stay as their last snapshot.

The existing dashboard server credential is reused. A single dashboard bet
owner is detected and remembered automatically. If the sync reports multiple
owners, set `MMA_DASHBOARD_BET_OWNER_ID=<your dashboard user UUID>` in the bot's
local `.env`. Find that UUID in Supabase Authentication → Users; it is not your
Discord user ID. This setting is only needed for that warning. A missing table,
ambiguous owner or incomplete ticket preserves the previous block and prints
a note in the sync window.

## Weekly workspace behavior

- Promotion analysis is limited to the current Monday–Sunday Chicago week.
- The week boundary is Monday 6:00 AM CT; channels roll over on the next
  successful publication after that boundary.
- Completed/past event channels move to the archive without deleting user bet
  notes, discussions, pins, or bot posts.
- One pinned fight-card message holds the full card; large cards use multiple
  embeds in that same message.
- A changed lineup or newly confirmed result adds one fresh full-card message
  with every current matchup, result and explicitly cancelled fight. Repeating
  the same refresh does not add another lineup. Order changes are included.
- Saved FightCenter bets appear in a pinned My Bets block; results and ROI
  remain in the dashboard.

## Launchers

- `01-PREVIEW.bat` — preview the expected private channel layout.
- `02-CREATE-CHANNELS.bat` — create/verify the layout and archive `#rizin`.
- `03-CHECK-SETUP.bat` — read-only layout/pin check.
- `04-CONNECT-DASHBOARD.bat` — connect this bot to the matching dashboard v12.
- `05-SYNC-THIS-WEEK.bat` — one manual dashboard-to-Discord publication.
- `06-KEEP-UPDATING.bat` — command listener plus daily coordinated publication.
- `07-INSTALL-COMMANDS.bat` — install/update Python and browser dependencies.

Run only one 05/06 updater at a time. The computer must remain awake, connected,
and running 06 for Discord automation and commands. The dashboard browser can
be closed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Dashboard provider-core mismatch | Install dashboard v12 and rerun 04 with that folder. |
| Discord waits at the morning sync | Open dashboard Data Health or inspect the daily task; Discord is protecting the old complete snapshot. |
| `#rizin` is still under Promotions | Run 02 once from v6. Messages are preserved. |
| No weekly event channel | Confirm the event exists in dashboard Data Health, run `npm run sync:now`, then run 05. |
| Command source cannot match safely | Add the exact event `source_url`/`odds_url` in `event-overrides.json`; never force an ambiguous match. |
| Bot offline | Keep one 06 window running and confirm the PC is awake/online. |
| Missing packages or Chromium | Run 07, then restart 06. |
| My Bets has not populated | Confirm a saved stake and accepted price in FightCenter, then stop 06, run 05 and restart 06. Inspect any saved-bet warning printed by 05. |
| Dashboard folder moved | Run 04 with the extracted working folder, then reinstall both tasks using the command below. |

Only if the dashboard folder moved, open PowerShell in the **new extracted
dashboard folder** containing `api`, `src`, `package.json` and your working
`api/.env`, and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-daily-sync.ps1
```

A path ending in `.zip` is the archive, not the working folder. Select the
folder created by **Extract All** and restore its working `api/.env` before
connecting. Do not run the task installer from the Discord bot folder.

## Verification

The v6.1 build passed 93 offline checks, including saved-bet reads and display,
complete cross-card parlays, owner binding, failed-read preservation, complete lineup posting,
unchanged-check deduplication, large cards, interrupted publication, user-note
preservation, command behavior, formatting, archives and odds-alert limits.
Live Discord and your database must be verified by the first local 05 run.

The release package intentionally excludes credentials, local state, tests,
fixtures, and the retired duplicated `event_sources` provider tree.
