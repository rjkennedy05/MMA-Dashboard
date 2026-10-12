from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EventFreshnessCache:
    """Avoid repeated distant-card reads while always refreshing fight week."""

    def __init__(self, path: Path, now: datetime | None = None) -> None:
        self.path = path
        self.now = now or datetime.now(timezone.utc)
        self.rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self.rows = {
                        str(key): value
                        for key, value in payload.items()
                        if isinstance(value, dict)
                    }
            except (OSError, ValueError):
                self.rows = {}

    @staticmethod
    def key(provider: str, external_id: Any) -> str:
        return f"{provider}:{external_id}"

    def should_refresh(
        self,
        provider: str,
        external_id: Any,
        event_date: date | None,
        listing: Any,
        *,
        force: bool = False,
    ) -> bool:
        if force or event_date is None:
            return True
        days = (event_date - self.now.date()).days
        # Results and the next week are always live work. Distant cards are
        # refreshed immediately when their listing changes, otherwise every
        # three days instead of every morning.
        if -2 <= days <= 7:
            return True
        stored = self.rows.get(self.key(provider, external_id))
        current_fingerprint = fingerprint(listing)
        if not stored or stored.get("fingerprint") != current_fingerprint:
            return True
        try:
            checked = datetime.fromisoformat(
                str(stored.get("checked_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            return True
        return self.now - checked >= timedelta(days=3)

    def mark(self, provider: str, external_id: Any, listing: Any) -> None:
        self.rows[self.key(provider, external_id)] = {
            "fingerprint": fingerprint(listing),
            "checked_at": self.now.isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)
