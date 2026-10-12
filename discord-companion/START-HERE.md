# MMA Discord Companion 6.3

Use this bot with **dashboard 12.1.0 / provider core 1.1** and the working
database upgraded through migration 035. It uses the dashboard's provider clients
and parsers. Keep your existing server and bot.

## Upgrade the existing installation

1. Stop the 06 runner and any active 05 updater.
2. Save the existing bot folder, especially `.env`, `setup-state.json`,
   `sync-state.json` and its recovery copies, `bot-settings.json`, and
   `event-overrides.json`.
3. Upgrade the dashboard and existing database using its
   `PERSONAL-RELIABILITY-12.1.md`. Copy this bot's new source over the working
   folder while preserving those local files.
4. Install Python **3.12**, then run `07-INSTALL-COMMANDS.bat`. It installs the
   locked packages and browser support. Run 04 if the dashboard folder changed.
5. Run a full daily dashboard refresh. Then run 05 and start 06; wait for READY.

05 follows the same completed-daily-refresh handshake as the automatic job.
Cards with source differences can post with visible data dispute markers. The
event header, affected fights and weekly index show an asterisk and a review
note. Missing matchups retain their saved status, bets and research. Markers
clear after a fresh source check resolves the difference; cached or unchecked
cards retain their prior markers. Updates and resolutions appear in card news.

This version needs the matching dashboard data-dispute update (readiness schema
3). The paired `MMA-personal-data-disputes-1.zip` installer updates both working
folders and backs up changed source automatically. No new SQL or dependencies
are required when upgrading 12.1.0 / companion 6.2 through that installer.
Run a full daily dashboard refresh after installation, then 05 and 06.

It keeps previous posts if the full refresh fails, its audit cannot finish, or
the database snapshot changes during the read.
The automatic job begins after 8 AM Central Time, and the long dashboard wait
allows commands to remain available.

The updated source preserves missing matchups, avoids stale manual overlays,
uses one current research display with saved revisions, recovers interrupted
post writes, keeps unresolved old cards open, and coordinates concurrent copies
publishing to the same project/server. Keep one normal runner open.

## Settings and recovery

Continue using the existing local `.env` connection. `MMA_DASHBOARD_PATH` must
point to the matching dashboard folder containing `api`, `src`, and `package.json`.
Optional `MMA_DASHBOARD_BET_OWNER_ID` binds saved bets to one existing account.
Optional `MMA_DISCORD_SUPABASE_KEY` overrides the dashboard's shared server key
with an already-configured dedicated key for the same project.

Keys stay in local settings or secure environment settings. Do not paste them
into chat. The bridge reads dashboard content and writes only publisher
coordination metadata to Supabase; it does not edit cards, research, bets or odds.

State saves maintain `.bak` and `.bak2` recovery copies. If all copies are corrupt,
restore a saved state file before publishing. Recreating state from scratch can
lose the mapping to your existing channels and posts.

The source archives do not contain your actual credentials, messages or local
state. See the dashboard's recovery instructions before changing versions.
The new single-ticket format remains in the database if you roll back; the older
dashboard does not display those new singles until upgraded again.
