"""Commit each normalized event card in one PostgreSQL transaction."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from types import SimpleNamespace
import sys

from .persistence import lease_arguments, rpc_value
from .database import CompleteQuery

# CLI and package imports must share one batch context, even when both module
# paths are used by a caller during the transition from the legacy scripts.
if __name__ == "api.providers.atomic":
    sys.modules.setdefault("providers.atomic", sys.modules[__name__])
elif __name__ == "providers.atomic":
    sys.modules.setdefault("api.providers.atomic", sys.modules[__name__])

_batch = ContextVar("mma_event_batch", default=None)
TABLES = {"event": "events", "fight": "fights", "fighter": "fighters"}


def wrap_import_client(client):
    if isinstance(client, AtomicImportClient):
        return client
    return AtomicImportClient(client) if hasattr(client, "postgrest") else client


class AtomicImportClient:
    def __init__(self, raw):
        self.raw = raw

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def table(self, name):
        current = _batch.get()
        query = CompleteQuery(self.raw.table(name), name)
        return (
            BatchQuery(self, name, query)
            if current and current.client is self
            else query
        )

    def rpc(self, name, arguments):
        current = _batch.get()
        if (
            current
            and current.client is self
            and name in {"mma_upsert_import_entity", "mma_find_external_identity"}
        ):
            return SimpleNamespace(
                execute=lambda: SimpleNamespace(data=current.operation(name, arguments))
            )
        return self.raw.rpc(name, arguments)


class BatchQuery:
    def __init__(self, client, table, query):
        self.client, self.table_name, self.query = client, table, query
        self.filters = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            if name in {"insert", "update", "upsert", "delete"}:
                raise RuntimeError(
                    "Split writes are not permitted inside an atomic event import."
                )
            if name in {"eq", "in_", "gt", "gte", "lt", "lte"}:
                self.filters.append((name, args[0], args[1]))
            self.query = getattr(self.query, name)(*args, **kwargs)
            return self

        return method

    def merge(self, rows):
        current = _batch.get()
        rows = deepcopy(rows)
        staged = current.rows.get(self.table_name, {}) if current else {}
        key = {
            "events": "event_id",
            "fights": "fight_id",
            "fighters": "fighter_id",
        }.get(self.table_name)
        if not key:
            return rows
        by_id = {row[key]: row for row in rows}
        for identity, row in staged.items():
            original = by_id.get(identity)
            combined = {**(original or {}), **deepcopy(row)}
            by_id.pop(identity, None)
            if all(
                self.matches(combined, *condition)
                if condition[1] in combined
                else original is not None and condition[1] not in row
                for condition in self.filters
            ):
                by_id[identity] = combined
        for row in by_id.values():
            if self.table_name == "fights" and current:
                for side in ("fighter_a", "fighter_b"):
                    fighter = current.rows.get("fighters", {}).get(
                        row.get(side + "_id")
                    )
                    if fighter:
                        row[side] = {**(row.get(side) or {}), **deepcopy(fighter)}
        return list(by_id.values())

    @staticmethod
    def matches(row, operation, key, value):
        current = row.get(key)
        if operation == "eq":
            return current == value
        if operation == "in_":
            return current in value
        if current is None:
            return False
        return {
            "gt": lambda: current > value,
            "gte": lambda: current >= value,
            "lt": lambda: current < value,
            "lte": lambda: current <= value,
        }[operation]()

    def execute(self):
        current = _batch.get()
        raw = getattr(self.query, "query", None)
        request = getattr(raw, "request", raw)
        params = getattr(request, "params", None)
        cache_key = (
            (self.table_name, str(params))
            if params is not None
            and self.table_name
            in {
                "fighters",
                "fights",
                "events",
                "weight_classes",
                "promotions",
                "data_sources",
            }
            else None
        )
        if cache_key and cache_key in current.read_cache:
            response = current.read_cache[cache_key]
        else:
            response = self.query.execute()
            if cache_key:
                current.read_cache[cache_key] = response
        return SimpleNamespace(
            data=self.merge(response.data or []), count=getattr(response, "count", None)
        )


class EventBatch:
    def __init__(self, client):
        self.client, self.operations, self.rows, self.identities = client, [], {}, {}
        self.temporary = 0
        self.saved_ids = {}
        self.event_states = {}
        self.read_cache = {}

    def operation(self, name, arguments):
        entity, source, external = (
            arguments["p_entity_type"],
            arguments["p_source_id"],
            arguments["p_external_id"],
        )
        identity_key = (entity, source, external)
        known = self.identities.get(identity_key)
        if name == "mma_find_external_identity":
            return (
                deepcopy(known)
                if known
                else rpc_value(self.client.raw.rpc(name, arguments).execute())
            )
        identity = arguments.get("p_existing_id")
        if identity is None:
            known = known or rpc_value(
                self.client.raw.rpc(
                    "mma_find_external_identity",
                    {
                        "p_entity_type": entity,
                        "p_source_id": source,
                        "p_external_id": external,
                    },
                ).execute()
            )
            identity = known.get("internal_id") if known else None
        new = identity is None
        if new:
            self.temporary -= 1
            identity = self.temporary
        table, key = TABLES[entity], entity + "_id"
        staged = self.rows.setdefault(table, {})
        row = staged.get(identity)
        if row is None:
            # PostgreSQL validates existence at commit. Reads overlay this
            # partial patch on the stored projection; no extra SELECT * per row.
            row = {key: identity}
        row.update(deepcopy(arguments["p_payload"]))
        staged[identity] = row
        operation = deepcopy(arguments)
        operation["temporary_id"] = identity if new else None
        self.operations.append(operation)
        self.identities[identity_key] = {
            "internal_id": identity,
            "external_id_map_id": None,
        }
        return {
            "status": "imported" if new else "updated",
            "internal_id": identity,
            "row": deepcopy(row),
        }

    def commit(self):
        if self.operations:
            result = rpc_value(
                self.client.raw.rpc(
                    "mma_apply_import_batch",
                    {
                        "p_operations": self.operations,
                        **lease_arguments(),
                    },
                ).execute()
            )
            self.saved_ids = {int(k): int(v) for k, v in result["ids"].items()}
            self.event_states = result.get("event_states") or {}


@contextmanager
def import_batch(client):
    # Unit adapters without a real SDK remain ordinary connection fixtures.
    if not isinstance(client, AtomicImportClient):
        yield None
        return
    if _batch.get() is not None:
        if _batch.get().client is not client:
            raise RuntimeError(
                "Nested card imports must share one database connection."
            )
        yield _batch.get()
        return
    batch = EventBatch(client)
    token = _batch.set(batch)
    try:
        yield batch
        batch.commit()
    finally:
        _batch.reset(token)
