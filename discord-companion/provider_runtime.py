"""Load the dashboard's provider core and enforce the shared release contract."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys

from setup_discord import SetupError

EXPECTED_PROVIDER_CORE_VERSION = "1.1"
EXPECTED_ACTIVE_PROMOTIONS = ("ufc", "dwcs", "pfl", "one", "bkfc", "lfa")
ARCHIVED_PROMOTIONS = ("rizin",)

_provider_root: Path | None = None
_manifest: dict | None = None


def configure_provider_core(dashboard) -> dict:
    """Validate and activate the provider implementation shipped by the dashboard."""
    global _provider_root, _manifest
    dashboard = Path(dashboard).expanduser().resolve()
    api_root = dashboard / "api"
    manifest_path = api_root / "providers" / "manifest.json"
    if not manifest_path.is_file():
        raise SetupError(
            "This Discord release requires the matching dashboard provider core. "
            "Select the personal reliability 12.1 dashboard folder in 04-CONNECT-DASHBOARD."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise SetupError("The dashboard provider manifest could not be read safely.") from None
    active = tuple(manifest.get("active_promotions") or ())
    archived = tuple(manifest.get("archived_promotions") or ())
    if manifest.get("provider_core_version") != EXPECTED_PROVIDER_CORE_VERSION:
        raise SetupError(
            f"Dashboard provider core {manifest.get('provider_core_version') or 'unknown'} is not compatible "
            f"with Discord core {EXPECTED_PROVIDER_CORE_VERSION}. Install the matching releases together."
        )
    if set(active) != set(EXPECTED_ACTIVE_PROMOTIONS) or set(archived) != set(ARCHIVED_PROMOTIONS):
        raise SetupError("Dashboard and Discord disagree about active promotions. Install the matching releases together.")
    api_value = str(api_root)
    if api_value not in sys.path:
        sys.path.insert(0, api_value)
    importlib.invalidate_caches()
    _provider_root = api_root / "providers"
    _manifest = manifest
    return manifest


def provider_manifest() -> dict:
    if _manifest is None:
        raise SetupError("The shared dashboard provider core has not been configured.")
    return _manifest


def provider_module(key: str, filename: str):
    if _provider_root is None:
        dashboard = os.environ.get("MMA_DASHBOARD_PATH", "").strip()
        if dashboard:
            configure_provider_core(dashboard)
        else:
            raise SetupError("Run 04-CONNECT-DASHBOARD so Discord can use the dashboard's provider core.")
    if key in ARCHIVED_PROMOTIONS:
        raise SetupError("RIZIN tracking is retired; saved dashboard and Discord history remains available.")
    if key not in {"espn_mma", "one_championship", "lfa", "bkfc", "fightodds"}:
        raise SetupError(f"Unknown shared provider: {key}")
    if filename not in {"client", "normalizer"}:
        raise SetupError("Only provider clients and normalizers can be loaded by Discord.")
    module = importlib.import_module(f"providers.{key}.{filename}")
    source = Path(module.__file__).resolve()
    if _provider_root not in source.parents:
        raise SetupError("Discord loaded a provider outside the selected dashboard folder; restart from the matching package.")
    return module
