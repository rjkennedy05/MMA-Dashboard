"""Event identity decisions: ambiguity must never mean a missing event."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


class AmbiguousEventError(RuntimeError):
    pass


def normalized_title(value):
    value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def matching_event(rows, name, promotion=None):
    target = normalized_title(name)
    exact = [row for row in rows if normalized_title(row["event_name"]) == target]
    if len(exact) == 1:
        return int(exact[0]["event_id"])
    if len(exact) > 1:
        raise AmbiguousEventError(
            f"Multiple stored events match {name}; review their provider identities."
        )
    # Only a numbered series gives a safe renamed-event fallback. Sharing a
    # date, or being the only row that day, cannot establish identity.
    if promotion in {"ufc", "pfl", "lfa", "bkfc"}:
        pattern = rf"\b{re.escape(promotion)}\s*(\d+)\b"
        number = re.search(pattern, target)
        if number:
            candidates = [
                row
                for row in rows
                if re.search(pattern, normalized_title(row["event_name"]))
                and re.search(pattern, normalized_title(row["event_name"])).group(1)
                == number.group(1)
            ]
            if len(candidates) == 1:
                return int(candidates[0]["event_id"])
            if len(candidates) > 1:
                raise AmbiguousEventError(
                    f"Multiple stored events match {name}; review their provider identities."
                )
    for row in rows:
        title = normalized_title(row["event_name"])
        first, second = (
            set(re.findall(r"\b\d+\b", target)),
            set(re.findall(r"\b\d+\b", title)),
        )
        if first and second and first.isdisjoint(second):
            continue
        if SequenceMatcher(None, target, title).ratio() >= 0.80:
            raise AmbiguousEventError(
                f"A similar stored event may be {name}; review its provider identity before creating another event."
            )
    return None
