#!/usr/bin/env python3
"""Discord event commands and a daily weekly-card sync; no article feeds."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys

from setup_discord import DiscordAPI, ROOT, SetupError
from sync_discord import (DatabaseReader, Publisher, chicago, clipped, ct_time, fetch_data,
                          fingerprint, local_config, normalized, odds_history, parsed_time, publish_cycle,
                          publish_event, promotion, read_env, split_text, sync_lock, week_window)
from direct_sources import SourceError, fetch_fight_card, fetch_odds
from provider_runtime import ARCHIVED_PROMOTIONS, configure_provider_core

COOLDOWN = 60
RUNNER_VERSION = "6.1"


def daily_slot(now, hour=8, minute=0):
    local = now.astimezone(chicago())
    day = local.date()
    if (local.hour, local.minute) < (hour, minute):
        day -= timedelta(days=1)
    return day.isoformat()


def settings(path):
    result = {"app_hour": 8, "app_minute": 0}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise SetupError("bot-settings.json must contain a settings object.")
        # Legacy V5 keys are accepted but cannot enable article feeds.
        unknown = set(saved) - set(result) - {"news_hour", "news_minute", "news_feeds"}
        if unknown:
            raise SetupError("bot-settings.json contains an unknown setting.")
        result.update({key: value for key, value in saved.items() if key in result})
    if type(result["app_hour"]) is not int or not 0 <= result["app_hour"] <= 23:
        raise SetupError("The app hour must be an integer from 0 to 23.")
    if type(result["app_minute"]) is not int or not 0 <= result["app_minute"] <= 59:
        raise SetupError("The app minute must be an integer from 0 to 59.")
    return result


class EventService:
    def __init__(self, api, setup, path, dashboard, options=None, overrides_path=None):
        self.api, self.setup, self.path, self.dashboard = api, setup, path, dashboard
        self.options = options or settings(ROOT / "bot-settings.json")
        self.overrides_path = overrides_path or ROOT / "event-overrides.json"

    def publisher(self):
        return Publisher(self.api, self.setup, self.path)

    def state(self):
        if not self.path.exists():
            return {"events": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def overrides(self, eid):
        if not self.overrides_path.exists():
            return {}
        value = json.loads(self.overrides_path.read_text(encoding="utf-8"))
        return value.get(eid, {})

    def resolve(self, guild_id, channel_id):
        if str(guild_id) != str(self.setup["guild_id"]):
            raise SetupError("Use this command in your MMA FightCenter server.")
        matches = [(eid, item) for eid, item in self.state().get("events", {}).items()
                   if str(item.get("channel_id")) == str(channel_id)]
        if len(matches) != 1:
            raise SetupError("Use this command inside an event channel, not a promotion or index channel.")
        eid, item = matches[0]
        if not item.get("fights") and not item.get("seed_fights"):
            raise SetupError("This card needs its initial app import. Stop 06, run 05 once, then restart 06.")
        return eid

    def claim(self, publisher, eid, command, now):
        item = publisher.state["events"][eid]
        attempts = item.setdefault("command_attempts", {})
        last = parsed_time(attempts.get(command))
        if last and (now - last).total_seconds() < COOLDOWN:
            raise SetupError("This command was just checked. Wait one minute before refreshing it again.")
        attempts[command] = now.isoformat()
        publisher.save()
        return item

    def refresh(self, guild_id, channel_id, command, now=None):
        now = now or datetime.now(timezone.utc)
        eid = self.resolve(guild_id, channel_id)
        publisher = self.publisher()
        item = publisher.state["events"][eid]
        # Validate event-channel privacy before reading sources or editing any posts.
        publisher.event_channel(item["event"])
        event = item["event"]
        if promotion(event) in ARCHIVED_PROMOTIONS:
            return "RIZIN tracking is retired. This archived card and its saved posts remain available."
        item = self.claim(publisher, eid, command, now)
        fights = item.get("fights") or item.get("seed_fights")
        links = item.get("source_records") or item.get("source_links") or []
        links = deepcopy(links)
        if item.get("external_card"):
            links.append(item["external_card"]["source_url"])
        override = self.overrides(eid)
        if command == "refreshfight":
            result = fetch_fight_card(event, fights, links, now, override,
                                      item.get("source_identities"), item.get("source_names"))
            item.update(external_card=result, source_identities=result["identities"], source_names=result["names"])
            publisher.save()  # A Discord interruption cannot lose the fresh source snapshot.
            event_links = list(dict.fromkeys(item.get("source_links", []) + [result["source_url"]]))
            notes = publish_event(publisher, result["event"], result["fights"], now, links=event_links,
                                  override=override, alert_prices=False)
            changes = len([n for n in notes if not n.startswith("Line movement")])
            suffix = "Full updated card posted." if changes else "No new changes."
            partial = " Partial source: unlisted matchups were preserved." if not result["complete"] else ""
            warnings = "".join("\n⚠️ " + message for message in result.get("warnings", [])[:3])
            return f"🥊 Refreshed **{event['event_name']}** — {len(result['fights'])} fights. {suffix}{partial}\nSource: {result['source']} • Checked {ct_time(now.isoformat())}{warnings}"
        if command != "refreshodds":
            raise SetupError("Unknown refresh command.")
        config = read_env(Path(self.dashboard).expanduser() / "api" / ".env")
        result = fetch_odds(event, fights, links, now, override, config)
        # Keep absent books and reject backwards provider timestamps.
        saved = {f"{r['fight_id']}:{r['fighter_id']}:{r.get('sportsbook_key')}": r for r in item.get("direct_odds", [])}
        for row in result["rows"]:
            key = f"{row['fight_id']}:{row['fighter_id']}:{row.get('sportsbook_key')}"
            old = saved.get(key, {})
            before, after = parsed_time(old.get("provider_updated_at")), parsed_time(row.get("provider_updated_at"))
            if before and after and after < before:
                continue
            saved[key] = row
        first = not item.get("independent_odds_baseline")
        item["direct_odds"] = list(saved.values())
        item["odds_source"] = {k: v for k, v in result.items() if k != "rows"}
        publisher.save()
        notes = publish_event(publisher, event, fights, now, odds_history(item["direct_odds"]),
                              override=override, reset_prices=first)
        item["independent_odds_baseline"] = True
        publisher.save()
        count = len([n for n in notes if n.startswith("Line movement")])
        outcome = "Baseline saved; future checks will compare against these prices." if first else f"{count} big swing(s) posted." if count else "No big swings found."
        return f"📈 Checked **{event['event_name']}** — odds available for {result['covered']}/{result['total']} active fights.\n{outcome}\nSource: {result['source']} • Checked {ct_time(now.isoformat())}"

    def due(self, job, now):
        if job != "app":
            return False
        state = self.state()
        runner = state.get("runner", {})
        retry = parsed_time(runner.get("app_retry_at"))
        if retry and retry > now:
            return False
        slot = daily_slot(now, self.options["app_hour"], self.options["app_minute"])
        return (runner.get("version") != RUNNER_VERSION or runner.get("app_slot") != slot
                or state.get("last_week") != week_window(now)[0].isoformat())

    def mark(self, publisher, job, now, success):
        runner = publisher.state.setdefault("runner", {})
        if success:
            runner[job + "_slot"] = daily_slot(now, self.options[job + "_hour"], self.options[job + "_minute"])
            runner[job + "_success"] = now.isoformat()
            runner.pop(job + "_retry_at", None)
            if job == "app":
                runner["version"] = RUNNER_VERSION
                publisher.state["last_week"] = week_window(now)[0].isoformat()
        else:
            runner[job + "_retry_at"] = (now + timedelta(hours=1)).isoformat()
        publisher.save()

    def sync_app(self, now=None):
        now = now or datetime.now(timezone.utc)
        previous = self.state()
        reader = DatabaseReader(self.dashboard)
        completed = reader.wait_for_daily_sync(now)
        data = fetch_data(reader, now, previous)
        publisher = self.publisher()
        overrides = json.loads(self.overrides_path.read_text(encoding="utf-8")) if self.overrides_path.exists() else {}
        publish_cycle(publisher, data, now, overrides)
        self.mark(publisher, "app", now, True)
        suffix = " (dashboard refresh finished with review items)" if completed.get("status") == "partial" else ""
        print("Daily app sync complete. This week's notes and event cards updated." + suffix)

    def failed_job(self, job, now):
        # This must still work while Discord REST is unavailable.
        state = self.state()
        state.setdefault("runner", {})[job + "_retry_at"] = (now + timedelta(hours=1)).isoformat()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)


def make_client(service, token):
    import discord
    from discord import app_commands

    class FightCenterClient(discord.Client):
        def __init__(self):
            intents = discord.Intents.none()
            intents.guilds = True  # No privileged message-content or member intent.
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self, fallback_to_global=False)
            self.work = asyncio.Lock()
            self.scheduler = None
            self.owner_id = None
            guild = discord.Object(id=int(service.setup["guild_id"]))

            async def refreshfight(interaction: discord.Interaction):
                await self.refresh(interaction, "refreshfight")

            async def refreshodds(interaction: discord.Interaction):
                await self.refresh(interaction, "refreshodds")

            for name, callback, description in (
                ("refreshfight", refreshfight, "Refresh this event's card and published results from its source"),
                ("refreshodds", refreshodds, "Check fresh odds for this event and report big swings"),
            ):
                command = app_commands.Command(name=name, description=description, callback=callback)
                command.guild_only = True
                command.default_permissions = discord.Permissions(administrator=True)
                self.tree.add_command(command, guild=guild)

        async def setup_hook(self):
            # Validate the saved private workspace before registering any commands.
            await asyncio.to_thread(service.publisher)
            info = await asyncio.to_thread(service.api.request, "GET", f"/guilds/{service.setup['guild_id']}")
            if not info.get("owner_id"):
                raise SetupError("Discord did not return the server owner; commands were not enabled.")
            self.owner_id = str(info["owner_id"])
            app = await asyncio.to_thread(service.api.request, "GET", "/oauth2/applications/@me")
            for command in self.tree.get_commands(guild=discord.Object(id=int(service.setup["guild_id"]))):
                # Upsert these two commands only. Do not bulk-overwrite unrelated commands.
                payload = {k: v for k, v in command.to_dict(self.tree).items()
                           if k in {"name", "description", "type", "options", "default_member_permissions", "nsfw"}}
                payload["default_member_permissions"] = str(payload["default_member_permissions"])
                await asyncio.to_thread(service.api.request, "POST",
                    f"/applications/{app['id']}/guilds/{service.setup['guild_id']}/commands", payload)
            self.scheduler = asyncio.create_task(self.daily_loop())

        async def on_ready(self):
            print("READY — /refreshfight and /refreshodds work inside your event channels.")
            opt = service.options
            print(f"App sync daily at {opt['app_hour']:02d}:{opt['app_minute']:02d} CT. Article feeds are disabled.")
            print("No five-minute database polling. Keep this window open and your computer awake; Ctrl+C stops it.")

        async def refresh(self, interaction, command):
            if str(interaction.user.id) != self.owner_id:
                await interaction.response.send_message("Only the server owner can run these refreshes.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                async with self.work:
                    message = await asyncio.to_thread(service.refresh, interaction.guild_id, interaction.channel_id, command)
            except SetupError as error:
                message = str(error)
            except Exception:
                message = "The refresh could not finish. Saved information was kept. Check the runner window and try again later."
                print("A command could not finish; no credential details were logged.")
            await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        async def daily_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                for job, action in (("app", service.sync_app),):
                    now = datetime.now(timezone.utc)
                    async with self.work:
                        try:
                            if service.due(job, now):
                                await asyncio.to_thread(action, now)
                        except Exception as error:
                            detail = str(error) if isinstance(error, SetupError) else "Saved information was kept."
                            print(job.title() + " check stopped: " + detail + " Retrying in one hour.")
                            try:
                                await asyncio.to_thread(service.failed_job, job, now)
                            except Exception:
                                print("The retry time could not be saved. Check that this folder is writable.")
                # Only the local clock/state is checked here; no database/source requests.
                await asyncio.sleep(30)

        async def close(self):
            if self.scheduler:
                self.scheduler.cancel()
            await super().close()

    return FightCenterClient()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        import discord
    except ImportError:
        raise SetupError("Run 07-INSTALL-COMMANDS.bat once before starting the command bot.") from None
    config = local_config()
    configure_provider_core(config["MMA_DASHBOARD_PATH"])
    setup_path = ROOT / "setup-state.json"
    if not setup_path.exists():
        raise SetupError("Keep the successful setup-state.json in this starter folder.")
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    if setup["guild_id"] != config["DISCORD_GUILD_ID"]:
        raise SetupError("The saved structure and connection belong to different servers.")
    service = EventService(DiscordAPI(config["DISCORD_BOT_TOKEN"]), setup, ROOT / "sync-state.json",
                           config["MMA_DASHBOARD_PATH"])
    with sync_lock():
        client = make_client(service, config["DISCORD_BOT_TOKEN"])
        try:
            client.run(config["DISCORD_BOT_TOKEN"], log_handler=None)
        except discord.LoginFailure:
            raise SetupError("The bot token was rejected. Run 04 with the current Bot-page token.") from None


if __name__ == "__main__":
    try:
        main()
    except (SetupError, ValueError, KeyError, OSError) as error:
        print("Bot stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Command bot stopped.")
