#!/usr/bin/env python3
"""Privately configure the weekly Discord updater on the user's computer."""
import getpass
import os
from pathlib import Path
import sys

from setup_discord import DiscordAPI, ROOT, SetupError, apply_setup, read_layout, snowflake
from sync_discord import DatabaseReader, chicago, read_env
from provider_runtime import configure_provider_core


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    chicago()
    import json
    state_path = ROOT / "setup-state.json"
    if not state_path.exists():
        raise SetupError("Copy this update into the folder that contains your successful setup-state.json.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    existing = read_env(ROOT / ".env")
    print("Connect the Discord updater to your working MMA dashboard. Credentials stay on this computer.")
    guild = state["guild_id"]
    print("Using the server ID from your completed setup.")
    token = getpass.getpass("Bot token (hidden; press Enter to keep an existing saved token): ").strip() or existing.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SetupError("A bot token is required. Use the value from your app's Bot page.")
    if token.startswith("Bot "):
        token = token[4:].strip()
    print("Enter the working dashboard's folder: the one containing api, src and package.json.")
    dashboard = input("Dashboard folder path: ").strip().strip("\"'") or existing.get("MMA_DASHBOARD_PATH", "")
    dashboard = str(Path(dashboard).expanduser().resolve())
    configure_provider_core(dashboard)
    reader = DatabaseReader(dashboard)
    # Validate both connections before saving any new credential.
    apply_setup(DiscordAPI(token), snowflake(guild, "Server ID"), read_layout(), state_path, check_only=True)
    reader.rows("events", [("select", "event_id"), ("event_id", "eq.-1")])
    existing.update(DISCORD_GUILD_ID=guild, DISCORD_BOT_TOKEN=token, MMA_DASHBOARD_PATH=dashboard)
    if any("\n" in value or "\r" in value for value in existing.values()):
        raise SetupError("Connection values must be single lines.")
    target = ROOT / ".env"
    temporary = ROOT / ".env.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for key, value in existing.items():
            handle.write(key + "=" + value + "\n")
    temporary.replace(target)
    print("Connections verified and saved locally. Run 05-SYNC-THIS-WEEK.bat next.")


if __name__ == "__main__":
    try:
        main()
    except (SetupError, ValueError, KeyError, OSError) as error:
        print("Connection stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Connection cancelled.")
