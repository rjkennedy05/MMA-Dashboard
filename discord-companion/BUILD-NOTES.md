# Discord companion build notes — version 6.1

## Version 6.1

- Card/date/status/order changes and confirmed results now publish one fresh
  complete card instead of only changed-item bullets. The pinned card is also
  updated. Combined card/result changes share one lineup post.
- Running order is saved in snapshots. Old snapshots learn it without a false
  change alert on the first refresh.
- Odds-only alerts retain the existing threshold and format; no provider
  routing or price-baseline behavior was changed.
- The existing research publication now reads recorded FightCenter singles
  from `fight_research` and complete parlays from `bet_tickets`/`bet_legs`.
  It replaces the old My Bets guide in place, retaining its message ID and pin.
- Bet blocks contain selections, stakes, accepted prices, sportsbooks, labels
  and every parlay leg. Cross-card tickets are copied whole to each relevant
  current-week card and labelled as one shared ticket.
- Archived/reset bets, drafts, leans, settlement fields, live progress and ROI
  are excluded. Add/edit/remove changes appear at the next research sync.
  Manual event commands preserve the last bet block without database reads.
- The bet owner is detected and saved before publication; ambiguous owners
  require the optional local `MMA_DASHBOARD_BET_OWNER_ID`. Legacy shared single
  rows remain compatible. Failed reads preserve the previous display while
  cards and research continue syncing.
- Long lists and tickets retain all content within Discord limits. Shrinking
  lists remove only redundant recorded bot bet pages after a local backup.
  User messages and pins remain untouched; archive bet displays remain frozen.
- Documentation distinguishes the manual bot's FightOdds-first path from the
  dashboard's The Odds API-first import. API-Sports is not a manual bot source.
- Dashboard v12/provider-core 1.0 and all preserved local state are compatible.
  An existing v6 installation needs files replaced, one 05 publication and
  06 restarted. No dashboard/schema/task/dependency/permission change is needed.
- 93 offline checks passed: saved-bet reads, cross-card completeness, owner
  binding, read failures, edit/removal behavior, long content and interrupted
  publication, plus full-card, publisher, command, formatting, archive,
  recovery and existing odds-alert regression checks. No user
  credentials were available for live Discord verification.

## Version 6.0 architecture

Version 6.0 was built against `MMA-Dashboard-phase8-reliability-v12.zip` and
replaces the v5.2 forked-provider architecture.

## Runtime changes

- `provider_runtime.py` requires shared provider-core version `1.0` and the
  exact active/archived promotion manifest.
- `direct_sources.py` imports read-only clients and normalizers from the
  connected dashboard. It no longer imports bundled provider copies.
- BKFC therefore receives the dashboard's XML/JSON MMAReg result correction,
  while UFC/DWCS/PFL receive the dashboard's latest ESPN identity and duplicate
  protections.
- FightOdds uses the same browser fallback and cleanup rules as the dashboard.
- Any attempted RIZIN direct refresh exits before constructing a network
  reader.
- Startup rejects an older/incompatible dashboard with one actionable error.

## Scheduling and handshake

- `DatabaseReader.latest_daily_sync` accepts only today's full
  `run_mode=daily`, `requested_scope=all` row.
- `wait_for_daily_sync` waits for success/partial, refuses a failed run, and
  times out after 75 minutes without publishing incomplete data.
- The existing one-hour job retry remains.
- The runner still uses America/Chicago for daily slots and Monday 6:00 AM
  rollover, independent of Windows' current UTC offset.

## RIZIN retirement

- The active layout contains six promotion channels.
- Setup finds an existing `#rizin`, moves it to the archive category, changes
  only its topic/parent, and records its ID.
- Existing messages and pins remain untouched.
- Saved RIZIN event channels encountered by the publisher are archived and
  marked retired; they cannot return to the current-week workspace.
- No new RIZIN promotion/event channel or provider request is created.

## Safety boundaries retained

- Supabase access is GET-only through an approved table list.
- Provider commands do not write to Supabase.
- Discord writes are limited to the configured private server and recorded bot
  posts/channels.
- Interaction commands defer privately before external work.
- Redirects, unsafe hosts, ambiguous event matches, guessed fighter matches,
  and incomplete source shrinkage are refused.
- State writes remain atomic and one folder lock prevents two updaters.

## Verification

The v6.0 architecture was verified with 116 tests, with 12 legacy RIZIN fixture tests
skipped because that provider is retired. Active checks cover provider sharing,
command authorization, private setup, RIZIN archival without message loss,
daily-run selection, wait-for-completion behavior, formatting, weekly rollover,
state recovery, direct result/odds preservation, and Discord message limits.

The v6.1 verification above covers the two approved changes. Further odds
movement work is deferred; the existing command is retained for compatibility.

The distributable omits tests, fixtures, credentials, user state, and the old
`event_sources` tree. Runtime provider code comes only from dashboard v12.
