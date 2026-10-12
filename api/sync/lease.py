"""One renewable database lease for CLI, scheduled, UI and maintenance imports."""

from __future__ import annotations

import os
from threading import Event, Thread
from uuid import uuid4

try:
    from providers.persistence import rpc_value
except ModuleNotFoundError:
    from api.providers.persistence import rpc_value


class ImportBusyError(RuntimeError):
    pass


class ImportLeaseLost(RuntimeError):
    pass


class SyncLease:
    def __init__(self, client, *, dry_run=False, seconds=180, interval=30):
        self.client, self.dry_run, self.seconds, self.interval = (
            client,
            dry_run,
            seconds,
            interval,
        )
        self.stop, self.lost = Event(), Event()
        self.thread, self.inherited = None, False
        self.previous = {
            name: os.environ.get(name)
            for name in ("MMA_SYNC_LEASE_HOLDER", "MMA_SYNC_LEASE_FENCE")
        }

    def _renew(self):
        return (
            rpc_value(
                self.client.rpc(
                    "mma_renew_sync_lease",
                    {
                        "p_holder": self.holder,
                        "p_fence": self.fence,
                        "p_seconds": self.seconds,
                    },
                ).execute()
            )
            is True
        )

    def _heartbeat(self):
        while not self.stop.wait(self.interval):
            try:
                if self._renew():
                    continue
            except Exception:
                pass
            self.lost.set()
            return

    def ensure_owned(self):
        if self.lost.is_set():
            raise ImportLeaseLost(
                "Refresh stopped because its database lease was lost; retry after the active import finishes."
            )

    def __enter__(self):
        if self.dry_run:
            return self
        self.inherited = bool(
            self.previous["MMA_SYNC_LEASE_HOLDER"]
            and self.previous["MMA_SYNC_LEASE_FENCE"]
        )
        self.holder = self.previous["MMA_SYNC_LEASE_HOLDER"] or str(uuid4())
        if self.inherited:
            self.fence = int(self.previous["MMA_SYNC_LEASE_FENCE"])
            if not self._renew():
                raise ImportLeaseLost(
                    "Parent import lease expired; child refresh refused."
                )
            return self
        result = rpc_value(
            self.client.rpc(
                "mma_claim_sync_lease",
                {
                    "p_holder": self.holder,
                    "p_seconds": self.seconds,
                },
            ).execute()
        )
        if not result or not result.get("acquired"):
            raise ImportBusyError(
                "Another dashboard import is running. Existing data was kept; try again when it finishes."
            )
        self.fence = int(result["fence"])
        os.environ["MMA_SYNC_LEASE_HOLDER"] = self.holder
        os.environ["MMA_SYNC_LEASE_FENCE"] = str(self.fence)
        self.thread = Thread(
            target=self._heartbeat, daemon=True, name="mma-import-heartbeat"
        )
        self.thread.start()
        return self

    def __exit__(self, *_args):
        if self.dry_run or self.inherited:
            return
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        try:
            self.client.rpc(
                "mma_release_sync_lease",
                {"p_holder": self.holder, "p_fence": self.fence},
            ).execute()
        finally:
            for name, value in self.previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
