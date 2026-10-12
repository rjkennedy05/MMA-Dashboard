# Discord companion build notes 6.2

This release pairs with dashboard 12.1.0, provider core 1.1 and migrations 031–035.
The original 6.1 source remains preserved in the baseline archive/tag.

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
