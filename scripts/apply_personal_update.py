"""Install a paired dashboard/bot source update with automatic recovery copies."""

import argparse
import os
from pathlib import Path
import sys

try:
    from scripts.apply_patch_bundle import (default_dashboard, install_patch, installation_folder,
                                           restore_patch, validate_patch)
except ModuleNotFoundError:
    from apply_patch_bundle import (default_dashboard, install_patch, installation_folder,
                                    restore_patch, validate_patch)


def install_pair(bundle, dashboard, companion):
    bundle = Path(bundle).resolve()
    targets = [(bundle / "dashboard", dashboard), (bundle / "companion", companion)]
    for patch, target in targets:
        validate_patch(patch, target)  # Both releases must pass before either is changed.
    backups = []
    try:
        for patch, target in targets:
            backup = install_patch(patch, target)
            if backup:
                backups.append(backup)
    except BaseException:
        for backup in reversed(backups):
            restore_patch(backup)
        raise
    return backups


def default_companion(dashboard, desktops=None):
    if desktops is None:
        desktops = [Path.home() / "Desktop", Path.home() / "OneDrive/Desktop"]
        if os.environ.get("OneDrive"):
            desktops.append(Path(os.environ["OneDrive"]) / "Desktop")
    # The user's working bot retained its older folder name after upgrading.
    for desktop in desktops:
        candidate = desktop / "MMA Tracker/discord/MMA-Discord-Starter-v1/MMA-Discord-Starter"
        if all((candidate / name).is_file() for name in ("sync_discord.py", "run_bot.py", ".env")):
            return candidate.resolve()
    choices = []
    for candidate in [Path(dashboard) / "discord-companion",
                      *(p.parent for desktop in desktops
                        if (desktop / "MMA Tracker/discord").is_dir()
                        for p in (desktop / "MMA Tracker/discord").glob("*/*/sync_discord.py"))]:
        if all((candidate / name).is_file() for name in ("sync_discord.py", "run_bot.py", ".env")):
            choices.append(candidate.resolve())
    choices = set(choices)
    return next(iter(choices)) if len(choices) == 1 else None


def choose(label, default):
    if default:
        print(f"\n{label}: {default}")
        value = input("Press Enter to use this folder, or paste the working folder path: ").strip()
        return value.strip('"') if value else str(default)
    return input(f"\nPaste the path to your working {label} folder: ").strip().strip('"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard")
    parser.add_argument("--companion")
    parser.add_argument("--from-checkout", action="store_true",
                        help="Build the paired source patch from this verified Git checkout.")
    args = parser.parse_args()
    print("MMA personal update: preserve settings and apply the paired source repairs.\n"
          "Let any refresh finish and stop Discord 05/06 before installing.")
    bundle = Path(__file__).resolve().parent
    if args.from_checkout:
        try:
            from scripts.build_personal_update import build_update
        except ModuleNotFoundError:
            from build_personal_update import build_update
        bundle = build_update()
        print("Verified update source: " + str(bundle))
    dashboard = args.dashboard or choose("MMA-Dashboard", default_dashboard())
    installation_folder(dashboard, "dashboard")
    companion = args.companion or choose("Discord bot", default_companion(dashboard))
    backups = install_pair(bundle, dashboard, companion)
    if backups:
        print("\nUpdate installed in both projects. Settings and Discord state were preserved.")
        for backup in backups:
            print("Recovery copy: " + str(backup))
    else:
        print("\nThis update is already installed in both projects.")
    print("Run the dashboard refresh from START-HERE.txt, then Discord 05 and 06.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nUpdate stopped: " + str(error), file=sys.stderr)
        raise SystemExit(1)
