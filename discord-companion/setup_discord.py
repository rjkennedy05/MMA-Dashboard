#!/usr/bin/env python3
"""Create the private MMA Discord channel layout using a Discord bot token.

Python 3.10+; standard library only. No dashboard or Supabase access.
"""
from __future__ import annotations

import argparse
import getpass
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
API = "https://discord.com/api/v10"
PERMISSIONS = {
    "Manage Channels": 1 << 4,
    "View Channels": 1 << 10,
    "Send Messages": 1 << 11,
    "Embed Links": 1 << 14,
    "Attach Files": 1 << 15,
    "Read Message History": 1 << 16,
    "Pin Messages": 1 << 51,
}
BOT_PERMISSIONS = sum(PERMISSIONS.values())
VIEW = PERMISSIONS["View Channels"]


class SetupError(Exception):
    pass


class APIError(SetupError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError("An API request was redirected; stopped before forwarding credentials.")


class DiscordAPI:
    def __init__(self, token):
        self.token = token
        self.opener = build_opener(NoRedirects())

    def request(self, method, route, payload=None):
        if not route.startswith("/") or "://" in route:
            raise SetupError("Invalid API route.")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": "Bot " + self.token,
                   "User-Agent": "DiscordBot (https://discord.com, 1.0)",
                   "Content-Type": "application/json"}
        if method != "GET":
            headers["X-Audit-Log-Reason"] = "MMA%20FightCenter%20workspace%20setup"
        for attempt in range(5):
            try:
                with self.opener.open(Request(API + route, data=body, headers=headers,
                                              method=method), timeout=30) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except HTTPError as error:
                raw = error.read()
                try:
                    details = json.loads(raw)
                except (ValueError, TypeError):
                    details = {}
                if error.code == 429:
                    delay = float(details.get("retry_after", 1))
                    if not math.isfinite(delay) or delay < 0 or delay > 60 or attempt == 4:
                        raise SetupError("Discord is rate-limiting setup. Wait and run setup again.") from None
                    time.sleep(delay + 0.1)
                    continue
                messages = {
                    401: "Bot token was rejected. Use the token from your app's Bot page.",
                    403: "Bot lacks access or permissions. Check its server installation and permission list.",
                    404: "Server, channel or message was not found. Check the server ID and setup state.",
                }
                raise APIError(messages.get(error.code,
                    f"Discord API returned HTTP {error.code} (code {details.get('code', 'unknown')})."), error.code) from None
            except (URLError, TimeoutError, OSError):
                # A failed POST could already have reached Discord. Do not replay it blindly.
                raise SetupError("Network request did not complete. Run setup again to reconcile existing channels.") from None
        raise SetupError("Discord did not complete the request.")


def read_layout():
    layout = json.loads((ROOT / "server-layout.json").read_text(encoding="utf-8"))
    keys, names = set(), set()
    for category in layout["categories"]:
        if category["key"] in keys or category["name"] in names:
            raise SetupError("Duplicate category in server-layout.json.")
        keys.add(category["key"])
        names.add(category["name"])
        for channel in category["channels"]:
            if channel["key"] in keys or not re.fullmatch(r"[a-z0-9-]{1,100}", channel["name"]):
                raise SetupError("Invalid or duplicate channel in server-layout.json.")
            keys.add(channel["key"])
    return layout


def load_environment():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID"}:
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def snowflake(value, label):
    if not re.fullmatch(r"[0-9]{17,20}", value):
        raise SetupError(f"{label} must be the numeric Discord ID, not a name or invite code.")
    return value


def credentials():
    load_environment()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not guild_id and sys.stdin.isatty():
        guild_id = input("Server ID (right-click server > Copy Server ID): ").strip()
    if not token and sys.stdin.isatty():
        token = getpass.getpass("Bot token (hidden; not saved): ").strip()
    if not token or not guild_id:
        raise SetupError("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in the local .env or run interactively.")
    if token.startswith("Bot "):
        token = token[4:].strip()
    return snowflake(guild_id, "Server ID"), token


def overwrite_list(guild_id, bot_id):
    return [{"id": guild_id, "type": 0, "allow": "0", "deny": str(VIEW)},
            {"id": bot_id, "type": 1, "allow": str(BOT_PERMISSIONS), "deny": "0"}]


def private_permissions(channel, guild_id, bot_id):
    overwrites = channel.get("permission_overwrites", [])
    everyone = next((o for o in overwrites if str(o["id"]) == guild_id and o["type"] == 0), {})
    bot = next((o for o in overwrites if str(o["id"]) == bot_id and o["type"] == 1), {})
    # The owner can always access these. Other explicit viewers and administrator roles
    # must be managed separately if friends are added later.
    return bool(int(everyone.get("deny", 0)) & VIEW) and not (int(everyone.get("allow", 0)) & VIEW) \
        and int(bot.get("allow", 0)) & BOT_PERMISSIONS == BOT_PERMISSIONS \
        and not (int(bot.get("deny", 0)) & BOT_PERMISSIONS)


def topic_for(category, channel):
    if category["key"] == "promotions":
        return f"{channel['label']} | Full card research, matchup analysis, outside opinions and our discussion."
    if category["key"] == "upcoming":
        return "Weekly event index | America/Chicago | Planned refresh: Monday at 6:00 AM CT."
    return "Past event index | Archived card channels and research remain available."


def intro_for(category, channel):
    if category["key"] == "promotions":
        return (f"**{channel['label']} — CARD RESEARCH**\n\n"
                "Full card breakdowns and our discussion belong here. Each card should cover fighter backgrounds, "
                "recent opponents and competition quality, style matchups, paths to victory, odds, betting relevance, "
                "lean and confidence. Long breakdowns can continue across consecutive messages.\n\n"
                "Individual event channels hold the fight-night card, news, line movement and My Bets.\n\n"
                "Research automation is being connected. You can paste a breakdown here now.")
    if category["key"] == "upcoming":
        return ("**THIS WEEK'S MMA CARDS**\n\n"
                "UFC • DWCS • LFA • PFL • ONE • BKFC\n"
                "Times are shown in Central Time.\n\n"
                "The event schedule has not been connected yet. Individual card channels will appear here once "
                "the weekly event job is running. Each will contain the poster, card details, fight order, prices, "
                "news and My Bets.\n\n"
                "Planned weekly rollover: Monday at 6:00 AM CT. Completed cards move to the archive; "
                "promotion-channel research remains available.")
    return ("**PAST CARDS**\n\n"
            "Completed event channels will move here during the weekly rollover, preserving their card information, "
            "news, line movement and My Bets.\n\n"
            "The archive is ready. The weekly event job has not been connected yet.")


def single_match(items, description):
    if len(items) > 1:
        raise SetupError(f"Multiple matches for {description}. Resolve duplicate names before setup.")
    return items[0] if items else None


def apply_setup(api, guild_id, layout, state_path, *, check_only=False):
    bot = api.request("GET", "/users/@me")
    if not bot.get("bot"):
        raise SetupError("A Discord bot token is required.")
    bot_id = str(bot["id"])
    guild = api.request("GET", f"/guilds/{guild_id}")
    if guild["name"] != layout["server_name"]:
        raise SetupError(f"Target server is {guild['name']!r}; expected {layout['server_name']!r}. "
                         "Check the ID, or update server_name in server-layout.json.")
    member = api.request("GET", f"/guilds/{guild_id}/members/{bot_id}")
    roles = api.request("GET", f"/guilds/{guild_id}/roles")
    role_ids = set(member["roles"]) | {guild_id}
    permissions = 0
    for role in roles:
        if str(role["id"]) in role_ids:
            permissions |= int(role["permissions"])
    if not (permissions & (1 << 3)) and permissions & BOT_PERMISSIONS != BOT_PERMISSIONS:
        missing = [name for name, bit in PERMISSIONS.items() if not permissions & bit]
        raise SetupError("Bot permissions missing: " + ", ".join(missing))
    print(f"Connected to {guild['name']} ({guild_id}) as {bot['username']}.")
    channels = api.request("GET", f"/guilds/{guild_id}/channels")
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if state and state.get("guild_id") != guild_id:
        raise SetupError("setup-state.json belongs to another server. Use a separate starter folder.")
    state.update({"guild_id": guild_id, "bot_id": bot_id})
    state.setdefault("channels", {})
    state.setdefault("messages", {})

    def save():
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(state_path)

    # Validate all matching resources before making any writes.
    for category in layout["categories"]:
        existing = single_match([c for c in channels if c["type"] == 4 and c["name"] == category["name"]], category["name"])
        if existing:
            if not private_permissions(existing, guild_id, bot_id):
                raise SetupError(f"Existing category {category['name']} has different permissions; "
                                 "setup will not change them. Rename it or set its private permissions manually.")
            for channel in category["channels"]:
                found = single_match([c for c in channels if c.get("parent_id") == existing["id"]
                                      and c["name"] == channel["name"]], channel["name"])
                if found and (found["type"] != 0 or found.get("topic") != topic_for(category, channel)
                              or not private_permissions(found, guild_id, bot_id)):
                    raise SetupError(f"Existing #{channel['name']} has different settings; setup will not overwrite it.")
    if check_only:
        for category in layout["categories"]:
            parent = single_match([c for c in channels if c["type"] == 4 and c["name"] == category["name"]], category["name"])
            if not parent:
                raise SetupError(f"Missing category: {category['name']}")
            for channel in category["channels"]:
                found = single_match([c for c in channels if c.get("parent_id") == parent["id"]
                                      and c["name"] == channel["name"]], channel["name"])
                if not found:
                    raise SetupError(f"Missing channel: #{channel['name']}")
                message_id = state["messages"].get(channel["key"])
                if not message_id:
                    raise SetupError(f"No saved guide message for #{channel['name']}. Run setup once.")
                message = api.request("GET", f"/channels/{found['id']}/messages/{message_id}")
                if not message.get("pinned") or str(message["author"]["id"]) != bot_id:
                    raise SetupError(f"Guide message for #{channel['name']} is missing its pin or author differs.")
        count = sum(len(category["channels"]) for category in layout["categories"])
        print(f"Verified: {len(layout['categories'])} categories, {count} active text channels, private permissions and pinned guides.")
        return state

    for category_index, category in enumerate(layout["categories"]):
        parent = single_match([c for c in channels if c["type"] == 4 and c["name"] == category["name"]], category["name"])
        if not parent:
            parent = api.request("POST", f"/guilds/{guild_id}/channels", {
                "name": category["name"], "type": 4, "position": category_index,
                "permission_overwrites": overwrite_list(guild_id, bot_id)})
            channels.append(parent)
            print("Created " + category["name"])
        state["channels"][category["key"]] = parent["id"]
        save()
        for index, channel in enumerate(category["channels"]):
            found = single_match([c for c in channels if c.get("parent_id") == parent["id"]
                                  and c["name"] == channel["name"]], channel["name"])
            if not found:
                found = api.request("POST", f"/guilds/{guild_id}/channels", {
                    "name": channel["name"], "type": 0, "parent_id": parent["id"],
                    "position": index, "topic": topic_for(category, channel),
                    "permission_overwrites": overwrite_list(guild_id, bot_id)})
                channels.append(found)
                print("Created #" + channel["name"])
            state["channels"][channel["key"]] = found["id"]
            save()
            content = intro_for(category, channel)
            # Own bot messages are available without the privileged message-content intent.
            messages = api.request("GET", f"/channels/{found['id']}/messages?limit=100")
            message_id = state["messages"].get(channel["key"])
            message = next((m for m in messages if str(m["author"]["id"]) == bot_id
                            and (m["id"] == message_id or m.get("content") == content)), None)
            if not message and message_id:
                # The stored guide may be older than the recent-message window.
                message = api.request("GET", f"/channels/{found['id']}/messages/{message_id}")
                if str(message["author"]["id"]) != bot_id:
                    raise SetupError("Saved guide message has an unexpected author.")
            if not message:
                message = api.request("POST", f"/channels/{found['id']}/messages", {
                    "content": content, "allowed_mentions": {"parse": []}})
            state["messages"][channel["key"]] = message["id"]
            save()
            if not message.get("pinned"):
                api.request("PUT", f"/channels/{found['id']}/messages/pins/{message['id']}")
    # Preserve the old RIZIN research channel and its messages, but move it out
    # of the active promotion workspace. No new RIZIN resources are created.
    retired = single_match([c for c in channels if c.get("type") == 0 and c.get("name") == "rizin"], "retired #rizin")
    if retired:
        archive_id = state["channels"]["archive"]
        if retired.get("parent_id") != archive_id:
            retired = api.request("PATCH", f"/channels/{retired['id']}", {
                "parent_id": archive_id,
                "topic": "RIZIN retired | Existing research is preserved; no new tracking or provider calls."
            })
            print("Moved #rizin to the archive; existing messages were preserved.")
        state["channels"]["rizin"] = retired["id"]
        save()
    print("Layout created. Checking the live channels and pins...")
    return apply_setup(api, guild_id, layout, state_path, check_only=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true", help="Preview only (default); no credentials or network.")
    modes.add_argument("--apply", action="store_true", help="Create categories, channels and pinned guides.")
    modes.add_argument("--check", action="store_true", help="Check the installed layout without changing Discord.")
    modes.add_argument("--invite", metavar="APPLICATION_ID", help="Print a bot installation link; no token needed.")
    args = parser.parse_args()
    layout = read_layout()
    if args.invite:
        print("https://discord.com/oauth2/authorize?" + urlencode({
            "client_id": snowflake(args.invite, "Application ID"), "scope": "bot applications.commands",
            "permissions": str(BOT_PERMISSIONS), "integration_type": "0"}))
        return
    if not args.apply and not args.check:
        print("MMA FightCenter — server setup preview\n")
        for category in layout["categories"]:
            print(category["name"] + ": " + ", ".join("#" + c["name"] for c in category["channels"]))
        count = sum(len(category["channels"]) for category in layout["categories"])
        print(f"\nCreates {len(layout['categories'])} categories, {count} active text channels and {count} pinned guides.")
        print("If an existing #rizin channel is present, setup moves it to the archive without deleting its messages.")
        print("New channels restrict normal member access; the server owner and bot can view them.")
        print("After structure setup: run 04 to connect the dashboard, then 05 to import this week's cards.")
        print("This preview made no Discord changes.")
        return
    guild_id, token = credentials()
    apply_setup(DiscordAPI(token), guild_id, layout, ROOT / "setup-state.json", check_only=args.check)


if __name__ == "__main__":
    try:
        main()
    except (SetupError, ValueError, KeyError) as error:
        print("Setup stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Setup cancelled.", file=sys.stderr)
        sys.exit(130)
