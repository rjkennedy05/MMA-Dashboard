# Discord data flow — version 6.1

## Ownership

| Content | Authoritative system | Discord behavior |
| --- | --- | --- |
| Event catalog and identities | Dashboard / Supabase | Reads current-week rows after the daily completion handshake |
| Cards, cancellations and results | Dashboard providers | Publishes snapshot; manual command may retain a newer direct observation |
| Fighter profiles and history | Dashboard / Supabase | Does not build a second history database |
| Odds history | Dashboard / Supabase | Manual event check keeps a local direct baseline for movement alerts |
| Full-card AI analysis | Dashboard event research | Publishes saved current-week analysis |
| Accepted singles and parlay tickets | Dashboard FightCenter | Copies bet details into pinned current-week My Bets blocks |
| Grading, live bet progress and ROI | Dashboard FightCenter | Does not publish or calculate these |
| Event-channel discussion and optional My Bets notes | Discord | Preserved during refreshes and archive moves |

## Morning sequence

1. The dashboard daily task creates one `running` sync row.
2. Catalog, active-card, recent-result, odds, and coverage stages run.
3. The same row becomes `success`, `partial`, or `failed`.
4. Discord waits for today's full `daily` / `all` row to finish.
5. On success or partial, Discord reads one snapshot of current cards, saved
   research and accepted bets through paginated GET requests, then publishes.
6. On failure or timeout, it keeps the previous snapshot and retries in one
   hour.

Weekly maintenance rows and per-promotion refresh rows cannot satisfy step 4.

## Shared provider core

`provider_runtime.py` validates provider-core version `1.0` from the connected
dashboard's `api/providers/manifest.json`. Direct commands load only the
dashboard clients/normalizers for ESPN MMA, ONE, LFA, BKFC, and FightOdds.
Database importers are not exposed through Discord.

The active manifest is UFC, DWCS, PFL, ONE, BKFC, and LFA. RIZIN is archived.
Discord contains no active RIZIN reader and makes no RIZIN network request.

## Direct observations

`/refreshfight` and `/refreshodds` are manual, bounded source reads. A direct
snapshot is stored in `sync-state.json` with its observation time. A later
dashboard import cannot replace a newer confirmed direct result with stale app
data. Empty cards, missing winners, partial odds, and failed providers preserve
the previous confirmed state.

Manual odds routing currently tries rendered FightOdds moneylines first, then
The Odds API if no usable prices are available and a key is configured. It
does not use API-Sports or fill a partial FightOdds board through the fallback.
The dashboard's scheduled importer uses a different provider priority.

A changed card/date/status/order or published result adds a fresh complete
lineup in the event channel. The pinned card also stays current. Unchanged
checks do not add another lineup; odds-only checks retain their swing alerts.

## Saved-bet publication

The same scheduled research job or manual 05 publication reads current-week
singles from `fight_research`. It finds parlay ticket IDs through `bet_legs`,
then reads each parent `bet_tickets` row with **all** its legs, including legs
from other cards. It never filters a ticket down to just this event's legs.

The pinned My Bets block shows selections, stake units, accepted odds and
sportsbook; parlays also include the ticket label and each leg's accepted
price. A cross-card parlay is labelled as one shared ticket and appears whole
on each relevant current-week card. Other-card legs do not create channels.

Only accepted, positive-stake, non-archived bets are displayed. Research leans,
drafts and bets archived by the tracking reset are excluded. A unique dashboard
bet owner is remembered in local state; if multiple owners are present, the
optional `MMA_DASHBOARD_BET_OWNER_ID` must select the intended dashboard UUID.
Shared legacy single-bet research rows remain compatible.

The existing guide's message ID and pin are reused. Changed details update that
block at the next publication; unchanged details remain quiet. Large lists use
complete continuation pages. An unavailable table, ambiguous owner or incomplete
ticket keeps the last display while card/research publication continues.
Archived events retain their last bet snapshot.

There is no immediate save trigger, separate bet polling or bet-status feed.
Settlement fields, results and ROI are neither queried nor included. Manual
refresh commands reuse the saved block without reading bets from Supabase.

The bot edits/prunes only message IDs it owns and records. Redundant generated
card, research, index and My Bets pages are backed up before removal. User
notes, their pins and discussion are preserved. No bets are written to Supabase.

## Deferred work

There is no paid AI generation, automatic article/X/YouTube collection, cloud
hosting or recurring live-event polling in v6.1. Further odds movement work,
live bet progress and grading/ROI feeds remain deferred.
