"""Verify the odds browser; reuse installed Chrome or install Playwright Chromium."""
import subprocess
import sys

from provider_runtime import configure_provider_core, provider_module
from sync_discord import local_config


def verify_browser():
    configure_provider_core(local_config()["MMA_DASHBOARD_PATH"])
    FightOddsClient = provider_module("fightodds", "client").FightOddsClient
    with FightOddsClient():
        pass  # Open/close a temporary empty profile, without visiting any website.


def main():
    try:
        verify_browser()
        print("Odds browser verified. Your installed Chromium/Chrome is ready.")
        return 0
    except Exception:
        print("Preparing Chromium for the odds reader...")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    if result.returncode:
        print("Browser preparation stopped. Install Google Chrome or complete the Chromium download, then run 07 again.")
        return 1
    try:
        verify_browser()
    except Exception:
        print("The odds browser could not start. Read the installation error and run 07 again.")
        return 1
    print("Odds browser verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
