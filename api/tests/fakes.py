"""Connection fixtures only; PostgreSQL transaction behavior has separate tests."""

from copy import deepcopy
from types import SimpleNamespace


def rpc(client, name, arguments):
    def execute():
        if name == "mma_apply_import_batch_resilient":
            result = rpc(client, "mma_apply_import_batch", arguments).execute()
            result.data["failed_groups"] = []
            return result
        rows = getattr(client, "rows", None)
        if not isinstance(rows, dict):
            rows = {
                "external_ids": client.external_ids,
                "fighters": getattr(client, "fighters", []),
            }
        if name == "mma_apply_import_batch":
            before, ids, results = deepcopy(rows), {}, []
            try:
                for operation in deepcopy(arguments["p_operations"]):
                    for key in (
                        "event_id",
                        "fighter_a_id",
                        "fighter_b_id",
                        "winner_id",
                    ):
                        if (
                            operation["p_payload"].get(key, 0) is not None
                            and operation["p_payload"].get(key, 0) < 0
                        ):
                            operation["p_payload"][key] = ids[
                                str(operation["p_payload"][key])
                            ]
                    if (
                        operation.get("p_existing_id") is not None
                        and operation["p_existing_id"] < 0
                    ):
                        operation["p_existing_id"] = ids[
                            str(operation["p_existing_id"])
                        ]
                    result = (
                        rpc(client, "mma_upsert_import_entity", operation)
                        .execute()
                        .data
                    )
                    if operation.get("temporary_id"):
                        ids[str(operation["temporary_id"])] = result["internal_id"]
                    results.append(result)
            except BaseException:
                rows.clear()
                rows.update(before)
                raise
            return SimpleNamespace(data={"ids": ids, "results": results})
        entity, source, external = (
            arguments["p_entity_type"],
            arguments["p_source_id"],
            arguments["p_external_id"],
        )
        mapping = next(
            (
                r
                for r in rows["external_ids"]
                if r["entity_type"] == entity
                and r["source_id"] == source
                and r["external_id"] == external
            ),
            None,
        )
        if mapping is None:
            mapping = next((r for r in getattr(client, "identity_aliases", [])
                            if r["entity_type"] == entity and r["source_id"] == source
                            and r["external_id"] == external), None)
        if name == "mma_find_external_identity":
            return SimpleNamespace(data=deepcopy(mapping))
        if name != "mma_upsert_import_entity":
            raise AssertionError("Unexpected test RPC: " + name)
        if (
            mapping
            and arguments.get("p_existing_id") is not None
            and arguments["p_existing_id"] != mapping["internal_id"]
        ):
            raise RuntimeError("Conflicting mapped identity requires review")
        table = {"fighter": "fighters", "event": "events", "fight": "fights"}[entity]
        rows.setdefault(table, [])
        key = entity + "_id"
        identity = arguments.get("p_existing_id") or (mapping or {}).get("internal_id")
        stored = next((r for r in rows[table] if r[key] == identity), None)
        status = "updated" if stored else "imported"
        if not stored:
            identity = (
                identity
                if identity is not None
                else max((r[key] for r in rows[table]), default=0) + 1
            )
            stored = {key: identity}
            rows[table].append(stored)
        stored.update(arguments["p_payload"])
        pointer = next(
            (
                r
                for r in rows["external_ids"]
                if r["entity_type"] == entity
                and r["source_id"] == source
                and r["internal_id"] == identity
            ),
            None,
        )
        if not pointer:
            pointer = {"external_id_map_id": len(rows["external_ids"]) + 1}
            rows["external_ids"].append(pointer)
        elif pointer.get("external_id") != external:
            if not hasattr(client, "identity_aliases"):
                client.identity_aliases = []
            client.identity_aliases.append(deepcopy(pointer))
        pointer.update(
            entity_type=entity,
            source_id=source,
            external_id=external,
            internal_id=identity,
            external_url=arguments.get("p_external_url"),
        )
        if mapping and mapping is not pointer and mapping in rows["external_ids"]:
            rows["external_ids"].remove(mapping)
        return SimpleNamespace(
            data={"status": status, "internal_id": identity, "row": deepcopy(stored)}
        )

    return SimpleNamespace(execute=execute)
