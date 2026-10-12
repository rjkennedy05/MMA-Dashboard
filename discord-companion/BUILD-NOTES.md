# Discord companion build notes 6.3

This release pairs with dashboard 12.1.0, provider core 1.1 and migrations 031–035.
The original 6.1 source remains preserved in the baseline archive/tag.

`card_disputes.py` carries event/fight review markers from readiness schema 3.
Unresolved card differences are publishable warnings. Completed per-card import
errors retain saved data with review markers, while incomplete runs and failed
audits still stop publication. Event IDs scope warnings to the right card;
fresh checked-event IDs allow resolved warnings to clear. The snapshot read
also checks that the saved run did not change while content was being read.

`database_snapshot.py` provides consistent content reads and publisher
coordination. `snapshot_merge.py` compares observation times and reconciles
synthetic bout/fighter IDs. `state_store.py` saves durable state with two recovery
copies. The updater journals post intent before sending, uses a stable research
display, and retains unresolved cards. `run_bot.py` releases the command lock
while waiting for the dashboard and respects the scheduled CT start time.

`test_reliability.py` exercises these paths offline, including real asynchronous
lock behavior, old/new snapshot reconciliation, ticket reads, state recovery,
source-side reversals and interrupted post recovery. PostgreSQL tests in the
dashboard verify snapshot/lease coordination and permissions separately.

Validation results and deployment risks are recorded in the dashboard release
guide and its generated validation report. Live Discord permissions and actual
posting were not tested without the existing connection settings. Nothing was
posted to the real server during implementation.
