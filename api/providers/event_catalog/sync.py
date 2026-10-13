from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .client import CATALOG_URLS, OfficialCatalogClient
from .importer import OfficialCatalogImporter
from .normalizer import parse_official_catalog


def sync_official_catalogs(
    supabase: Any,
    *,
    requested_scope: str = "all",
    dry_run: bool = False,
    past_days: int = 30,
    future_days: int = 90,
) -> dict[str, Any]:
    catalog_keys = []
    if requested_scope in {"all", "ufc", "dwcs"}:
        catalog_keys.append("ufc")
    if requested_scope in {"all", "pfl"}:
        catalog_keys.append("pfl")
    if not catalog_keys:
        return {
            "status": "skipped_scope",
            "requests": 0,
            "catalogs": {},
            "issues": [],
        }

    client = OfficialCatalogClient()
    importer = OfficialCatalogImporter(supabase)
    today = date.today()
    start, end = today - timedelta(days=past_days), today + timedelta(days=future_days)
    result: dict[str, Any] = {
        "status": "completed",
        "requests": 0,
        "catalogs": {},
        "issues": [],
    }

    for catalog in catalog_keys:
        metrics = {
            "status": "running",
            "events": 0,
            "matched": 0,
            "imported": 0,
            "missing": 0,
            "failures": 0,
        }
        result["catalogs"][catalog] = metrics
        try:
            html, source_url = client.get_catalog(catalog)
            entries = [
                row
                for row in parse_official_catalog(html, catalog, source_url)
                if start <= row["date"] <= end
                and (
                    requested_scope in {"all", catalog}
                    or row["promotion_key"] == requested_scope
                )
            ]
            metrics["events"] = len(entries)
            metrics["source"] = CATALOG_URLS[catalog]
            if not entries:
                raise RuntimeError(
                    f"{catalog.upper()} official catalog returned no dated events in the coverage window."
                )
            for entry in entries:
                try:
                    imported = importer.import_event(entry, dry_run=dry_run)
                    state = imported["status"]
                    if state == "imported":
                        metrics["imported"] += 1
                    elif state == "missing":
                        metrics["missing"] += 1
                        result["issues"].append({
                            "code": "MISSING_EVENT",
                            "severity": "warning",
                            "promotion": entry["promotion_key"].upper(),
                            "event_name": entry["name"],
                            "event_date": entry["date"].isoformat(),
                            "message": "Official catalog event is not present in the dashboard.",
                        })
                    else:
                        metrics["matched"] += 1
                except Exception as error:
                    metrics["failures"] += 1
                    result["issues"].append({
                        "code": "CATALOG_IMPORT_FAILED",
                        "severity": "warning",
                        "promotion": entry["promotion_key"].upper(),
                        "event_name": entry["name"],
                        "event_date": entry["date"].isoformat(),
                        "message": str(error),
                    })
            metrics["status"] = "partial" if metrics["failures"] else "completed"
        except Exception as error:
            metrics.update(status="failed", failures=metrics["failures"] + 1, message=str(error))
            result["issues"].append({
                "code": "CATALOG_UNAVAILABLE",
                "severity": "warning",
                "promotion": "UFC / DWCS" if catalog == "ufc" else "PFL",
                "message": str(error),
            })

    result["requests"] = client.request_count
    if any(row["status"] == "failed" for row in result["catalogs"].values()):
        result["status"] = "partial"
    return result
