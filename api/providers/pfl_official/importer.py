"""Reuse the shared identity/transaction importer with official PFL provenance."""

from ..espn_mma.importer import PflImporter, utc_now
from ..event_catalog.importer import SOURCE_NAMES
from ..persistence import save_entity


class OfficialPflImporter(PflImporter):
    def _get_source_id(self):
        rows = (self.supabase.table("data_sources").select("source_id")
                .eq("name", SOURCE_NAMES["pfl"]).limit(1).execute().data or [])
        if len(rows) != 1:
            raise RuntimeError("The existing official PFL catalog source is missing. Verify migration 030.")
        return int(rows[0]["source_id"])

    def import_event(self, event, dry_run=False):
        mapping = self._external_mapping("event", event["external_id"])
        event_id = (int(mapping["internal_id"]) if mapping else
                    self._find_existing_event(event["name"], event["event_date"], self.promotion_id))
        if dry_run:
            return {"status": "dry_run", "event_id": event_id}
        payload = {"promotion_id": self.promotion_id, "event_name": event["name"],
                   "event_date": event["event_date"], "updated_at": utc_now()}
        payload.update({k: event[k] for k in ("event_status", "event_start_time", "venue", "city", "country")
                        if event.get(k) is not None})
        saved = save_entity(self.supabase, "event", payload, self.source_id,
                            event["external_id"], event_id, event["external_url"])
        return {"status": saved["status"], "event_id": int(saved["internal_id"])}
