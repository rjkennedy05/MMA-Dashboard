"""Build the existing paired installer input from a clean, committed checkout."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = "7419162b3d64ab6b98e27ad23eff534c0fbafe32"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True).stdout


def build_update(root=ROOT, base=BASE, output=None):
    """Keep both installed folders; never transfer credentials or bot state."""
    root = Path(root).resolve()
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("The source checkout has local edits. Commit or preserve them before building an update.")
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    paths = git(root, "diff", "--name-status", "-z", base, commit).decode().split("\0")
    files = {"dashboard": {}, "companion": {}}
    payloads = {"dashboard": {}, "companion": {}}
    try:
        from scripts.apply_patch_bundle import relative_file
    except ModuleNotFoundError:
        from apply_patch_bundle import relative_file
    for index in range(0, len(paths)-1, 2):
        status, name = paths[index:index+2]
        if status not in {"A", "M"}:
            raise ValueError("This update requires a reviewed installer for removed or renamed files: " + name)
        component = "companion" if name.startswith("discord-companion/") else "dashboard"
        relative = name.removeprefix("discord-companion/") if component == "companion" else name
        relative_file(relative)  # Refuse settings, unsafe paths and runtime data.
        data = git(root, "show", commit+":"+name)
        # The live checkout must match its committed payload, including symlinks.
        target = root / name
        if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
            raise ValueError("The source payload differs from its commit: " + name)
        original = git(root, "show", base+":"+name) if status == "M" else None
        digest = lambda value: hashlib.sha256(value).hexdigest() if value is not None else None
        files[component][relative] = {"sha256": digest(data), "allowed_before": [digest(original)]}
        payloads[component][relative] = data
    if not any(files.values()):
        raise ValueError("There are no source repairs after the supported checkpoint.")
    output = Path(output).resolve() if output else Path(tempfile.mkdtemp(prefix="mma-git-update-"))
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty update output folder.")
    output.mkdir(parents=True, exist_ok=True)
    try:
        for component in files:
            folder = output / component
            folder.mkdir()
            for name, data in payloads[component].items():
                target = folder / "payload" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (folder / "PATCH-MANIFEST.json").write_text(json.dumps({"patch": "reliability-repairs-"+commit[:12],
                "component": component, "base_commit": base, "source_commit": commit,
                "files": files[component]}, indent=2))
    except BaseException:
        shutil.rmtree(output)
        raise
    return output
