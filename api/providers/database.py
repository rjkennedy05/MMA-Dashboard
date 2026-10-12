"""Bounded, complete reads shared by provider adapters and maintenance."""

from __future__ import annotations

from typing import Any, Callable
from copy import copy
from types import SimpleNamespace

TABLE_KEYS = {
    "events": "event_id",
    "fighters": "fighter_id",
    "fights": "fight_id",
    "external_ids": "external_id_map_id",
    "data_sources": "source_id",
    "promotions": "promotion_id",
    "weight_classes": "weight_class_id",
    "odds": "odds_id",
    "mma_odds_observations": "observation_id",
    "fighter_history_entries": "fighter_history_entry_id",
    "fighter_history_coverage": "fighter_id",
}


class CompleteQuery:
    """SDK reads without an explicit limit must survive PostgREST row caps."""

    def __init__(self, query, table):
        self.query, self.table = query, table
        self.read, self.bounded, self.ordered = False, False, False

    def __getattr__(self, name):
        def method(*args, **kwargs):
            if name == "select":
                self.read = True
            if name in {"insert", "upsert", "update", "delete"}:
                self.read = False
                self.bounded = True
            if name in {"limit", "range", "single", "maybe_single"}:
                self.bounded = True
            if name == "order":
                self.ordered = True
            self.query = getattr(self.query, name)(*args, **kwargs)
            return self

        return method

    def execute(self):
        key = TABLE_KEYS.get(self.table)
        if not self.read or self.bounded or not key:
            return self.query.execute()
        # Copy once: paging must not accumulate predicates on a reusable query.
        query = copy(self.query)
        if hasattr(query, "request"):
            query.request = copy(self.query.request)
            query.request.params = copy(self.query.request.params)
        else:
            query.params = copy(self.query.params)
        if hasattr(query, "request"):
            ordering = query.request.params.get("order")
            query.request.params = query.request.params.set(
                "order", (ordering + "," if ordering else "") + key + ".asc"
            )
        else:
            query = query.order(key)
        rows, previous = [], None
        for _ in range(2000):
            page_query = copy(query)
            if hasattr(query, "request"):
                page_query.request = copy(query.request)
                page_query.request.params = copy(query.request.params)
            else:
                page_query.params = copy(query.params)
            response = page_query.range(len(rows), len(rows) + 499).execute()
            page = response.data or []
            if not page:
                return SimpleNamespace(
                    data=rows, count=getattr(response, "count", None)
                )
            if page == previous:
                raise RuntimeError(
                    "Database pagination did not advance; incomplete data refused."
                )
            rows.extend(page)
            previous = page
        raise RuntimeError(
            "Database read exceeded its page limit; incomplete data refused."
        )


def read_rows(
    query_factory: Callable, key: str, page_size: int = 500
) -> list[dict[str, Any]]:
    """Keyset pagination survives server row caps without relying on page length."""
    rows, seen, last = [], set(), None
    for _ in range(2000):
        query = query_factory().order(key).limit(page_size)
        if last is not None:
            query = query.gt(key, last)
        page = query.execute().data or []
        if not page:
            return rows
        for row in page:
            identity = row[key]
            if identity in seen:
                raise RuntimeError(
                    f"Database pagination repeated {key}; incomplete data was refused."
                )
            seen.add(identity)
            rows.append(row)
        last = page[-1][key]
    raise RuntimeError(
        "Database read exceeded its safe page limit; incomplete data was refused."
    )


def table_rows(client: Any, table: str, columns: str, key: str, filters=None):
    def query():
        raw = getattr(client, "raw", client)
        result = raw.table(table).select(columns)
        return filters(result) if filters else result

    rows = read_rows(query, key)
    merged = client.table(table).select(columns)
    if filters:
        merged = filters(merged)
    # Avoid virtual IDs interfering with physical keyset pagination.
    return merged.merge(rows) if hasattr(type(merged), "merge") else rows
