"""One consistent card read and a server-wide publishing lease."""

from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4


class SnapshotReader:
    def __init__(self, tables, owner_id=None):
        self.tables, self.bet_owner_id = tables, owner_id

    def rows(self, table, params):
        rows = self.tables.get(table, [])

        def value(row, key):
            for part in key.split("."):
                if isinstance(row, list):
                    row = row[0] if row else {}
                row = row.get(part) if isinstance(row, dict) else None
            return row

        for key, rule in params:
            if key == "select":
                continue
            if rule.startswith("in.("):
                allowed = rule[4:-1].split(",")
                rows = [r for r in rows if str(value(r, key)) in allowed]
            elif rule == "is.null":
                rows = [r for r in rows if value(r, key) is None]
            elif rule == "not.is.null":
                rows = [r for r in rows if value(r, key) is not None]
            elif rule.startswith("eq."):
                rows = [r for r in rows if str(value(r, key)) == rule[3:]]
            elif rule.startswith("gt."):
                rows = [r for r in rows if float(value(r, key) or 0) > float(rule[3:])]
            elif rule.startswith("gte."):
                rows = [r for r in rows if str(value(r, key) or "") >= rule[4:]]
            elif rule.startswith("lt."):
                rows = [r for r in rows if str(value(r, key) or "") < rule[3:]]
            else:
                raise ValueError("Unsupported snapshot filter: " + key)
        return rows


@contextmanager
def publisher_lease(reader, guild):
    from setup_discord import SetupError

    holder = str(uuid4())
    stop = Event()
    lost = Event()

    def action(kind):
        return (
            reader.control_rpc(
                "mma_discord_publisher",
                {"p_guild": str(guild), "p_holder": holder, "p_action": kind},
            )
            is True
        )

    if not action("claim"):
        raise SetupError(
            "Another copy of this bot is publishing. Saved posts were kept; try again after it finishes."
        )

    def heartbeat():
        while not stop.wait(30):
            try:
                if action("renew"):
                    continue
            except Exception:
                pass
            lost.set()
            return

    worker = Thread(target=heartbeat, daemon=True)
    worker.start()

    def ensure():
        if lost.is_set():
            raise SetupError(
                "The publishing lease expired. Saved posts were kept; retry after the other bot finishes."
            )

    try:
        yield ensure
    finally:
        stop.set()
        worker.join(timeout=5)
        try:
            action("release")
        except Exception:
            pass  # Database expiry still releases an interrupted bot.
