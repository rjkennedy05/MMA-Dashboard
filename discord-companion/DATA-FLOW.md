# Discord data flow 6.2

The dashboard discovers official events, refreshes complete cards under one
database lease, records separate price observations, and saves an explicit daily
publication-readiness flag. A scoped, odds-only or maintenance run cannot replace
that handshake. Optional odds/history gaps do not claim full coverage.

After today's verified daily run, the bot requests one consistent JSON snapshot
of relevant events, fights, compact odds, research, links and tickets. Snapshot
reads refuse an active import. Private bet panels bind to an existing owner and
preserve their prior display if the snapshot is ambiguous or incomplete.

Direct commands reuse provider core 1.1 clients/normalizers. Manual observations
have timestamps, preserve omitted bouts and known results, and reconcile their
temporary identities when a newer dashboard card appears. Partial odds checks
retain absent books; older provider quotes cannot manufacture a movement.

The daily dashboard wait runs outside the command lock. Actual publishing and
state edits are serialized. A project/server-wide publishing lease prevents
concurrent upgraded bot copies from duplicating a cycle. Each mutating Discord
request checks lease ownership; durable post intents recover accepted posts when
their response was lost.

Research has a stable current display per event. Prior revisions and removed
generated chunks remain in local state backups. Older channels archive only
after their tracked bouts resolve. The archive index includes all retained
channels rather than the first forty.

Content remains read-only from the bot's perspective. Supabase writes are
limited to publisher coordination metadata. The server credential remains
privileged; a dedicated scoped credential requires authentication configuration
in the actual project. No hosting, commercialization or continuous live polling
was added in this personal reliability release.
