"""Apply a checksum-verified source patch and keep an automatic recovery copy."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def dashboard_folder(path):
    root = Path(path).expanduser().resolve()
    try:
        version = json.loads((root / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("Choose the MMA-Dashboard folder containing api, src, and package.json.") from error
    if version != "12.1.0" or not (root / "src").is_dir() or not (root / "api/sync/weekly_sync.py").is_file():
        raise ValueError("This patch needs your existing dashboard 12.1.0 folder.")
    return root


def relative_file(value):
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or ".." in path.parts or "\\" in value
            or ":" in value or any(part.lower().startswith(".env") for part in path.parts)
            or not (path.parts[0] in {"api", "scripts"} or (len(path.parts) == 1 and path.suffix == ".md"))):
        raise ValueError("The patch contains an unsupported file path.")
    return Path(*path.parts)


def within(root, relative):
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("A patch path points outside the selected folder.")
    return target


def replace_bytes(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".mma-patch-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def restore_patch(backup, only=None):
    backup = Path(backup).resolve()
    record = json.loads((backup / "RESTORE.json").read_text())
    root = dashboard_folder(record["dashboard"])
    files = record["files"] if only is None else {name: record["files"][name] for name in only}
    changes = []
    # Verify every selected file before restoring anything. Later user edits
    # are never overwritten by this recovery operation.
    for name, item in files.items():
        relative = relative_file(name)
        target = within(root, relative)
        current = digest(target)
        if current == item["before"]:
            continue
        if current != item["after"]:
            raise ValueError(f"This file changed after the patch; recovery stopped: {name}")
        original = within(backup / "files", relative)
        if item["before"] is not None and digest(original) != item["before"]:
            raise ValueError(f"The recovery copy could not be verified: {name}")
        changes.append((target, original, item))
    for target, original, item in changes:
        if item["before"] is None:
            target.unlink(missing_ok=True)
        else:
            replace_bytes(target, original.read_bytes())
    return root


def install_patch(bundle, dashboard):
    bundle = Path(bundle).resolve()
    root = dashboard_folder(dashboard)
    manifest = json.loads((bundle / "PATCH-MANIFEST.json").read_text())
    payload = bundle / "payload"
    changes = []
    for name, item in manifest["files"].items():
        relative = relative_file(name)
        source, target = within(payload, relative), within(root, relative)
        if digest(source) != item["sha256"]:
            raise ValueError(f"The downloaded patch file could not be verified: {name}. Extract the ZIP again.")
        before = digest(target)
        if before == item["sha256"]:
            continue
        if before not in item["allowed_before"]:
            raise ValueError(f"This file differs from the supported releases; nothing was changed: {name}")
        changes.append((name, relative, source, target, before, item["sha256"]))
    if not changes:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = root.parent / "MMA-patch-backups" / ("mma-patch-" + stamp)
    backup.mkdir(parents=True)
    record = {"dashboard": str(root), "patch": manifest["patch"], "files": {}}
    for name, relative, source, target, before, after in changes:
        if before is not None:
            destination = within(backup / "files", relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
            if digest(destination) != before:
                raise ValueError("A source file changed while it was being backed up. Retry after stopping the old programs.")
        record["files"][name] = {"before": before, "after": after}
    (backup / "RESTORE.json").write_text(json.dumps(record, indent=2) + "\n")
    shutil.copy2(Path(__file__), backup / "apply_patch_bundle.py")
    (backup / "RESTORE-PATCH.bat").write_text(
        '@echo off\ncd /d "%~dp0"\nwhere py >nul 2>nul\n'
        'if errorlevel 1 (\n  python "%~dp0apply_patch_bundle.py" --restore "%~dp0"\n'
        ') else (\n  py -3.12 "%~dp0apply_patch_bundle.py" --restore "%~dp0"\n)\npause\n')
    written = []
    try:
        for name, relative, source, target, before, after in changes:
            if digest(target) != before:
                raise ValueError(f"A file changed while the patch was installing: {name}")
            replace_bytes(target, source.read_bytes())
            written.append(name)
            if digest(target) != after:
                raise ValueError(f"The installed file could not be verified: {name}")
    except Exception:
        restore_patch(backup, only=written)
        raise
    return backup


def default_dashboard():
    desktops = [Path.home() / "Desktop", Path.home() / "OneDrive/Desktop"]
    if os.environ.get("OneDrive"):
        desktops.append(Path(os.environ["OneDrive"]) / "Desktop")
    found = set()
    for desktop in desktops:
        path = desktop / "MMA Tracker/MMA-FightCenter-personal-reliability-12.1.0/MMA-Dashboard"
        if path.is_dir():
            found.add(path.resolve())
    return next(iter(found)) if len(found) == 1 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard")
    parser.add_argument("--restore")
    args = parser.parse_args()
    if args.restore:
        root = restore_patch(args.restore)
        print(f"Restored the files saved before this patch: {root}")
        return 0
    selected = args.dashboard
    if not selected:
        default = default_dashboard()
        print("MMA Dashboard PFL card update\nStop Discord 06 and any active refresh before continuing.\n")
        if default:
            print(f"Your dashboard folder: {default}")
            selected = input("Press Enter to use that folder, or paste another dashboard folder path: ").strip() or str(default)
        else:
            selected = input("Paste the MMA-Dashboard folder path (the folder with api and src): ").strip()
        selected = selected.strip('"')
    backup = install_patch(Path(__file__).resolve().parent, selected)
    if backup:
        print(f"\nPatch installed. Your settings were preserved.\nBackup saved in: {backup}")
    else:
        print("\nThis patch is already installed.")
    print("Return to your dashboard PowerShell window and run the refresh command in START-HERE.txt.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"\nUpdate stopped: {error}\nRead this message before closing the window.", file=sys.stderr)
        raise SystemExit(1)
