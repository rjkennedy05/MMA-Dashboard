"""Atomic provider identities; no unsafe fallback to split database writes."""

from __future__ import annotations

import os
from datetime import datetime, timezone


def rpc_value(response):
    value = response.data
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def lease_arguments():
    holder = os.environ.get("MMA_SYNC_LEASE_HOLDER")
    fence = os.environ.get("MMA_SYNC_LEASE_FENCE")
    return {"p_holder": holder, "p_fence": int(fence) if fence else None}


def find_identity(client, entity, source_id, external_id):
    return rpc_value(
        client.rpc(
            "mma_find_external_identity",
            {
                "p_entity_type": entity,
                "p_source_id": source_id,
                "p_external_id": str(external_id),
            },
        ).execute()
    )


def save_entity(
    client,
    entity,
    payload,
    source_id,
    external_id,
    existing_id=None,
    external_url=None,
    *,
    catalog=False,
):
    result = rpc_value(
        client.rpc(
            "mma_upsert_import_entity",
            {
                "p_entity_type": entity,
                "p_payload": payload,
                "p_source_id": source_id,
                "p_external_id": str(external_id),
                "p_existing_id": existing_id,
                "p_external_url": external_url,
                "p_catalog": catalog,
                **lease_arguments(),
            },
        ).execute()
    )
    if not isinstance(result, dict) or result.get("internal_id") is None:
        raise RuntimeError(
            "Atomic import did not return a saved identity. Verify migration 032."
        )
    return result


def observation_time():
    return datetime.now(timezone.utc).isoformat()


def save_rows(client, table, rows):
    return (
        client.rpc(
            "mma_write_import_rows",
            {
                "p_table": table,
                "p_rows": rows,
                **lease_arguments(),
            },
        )
        .execute()
        .data
    )
