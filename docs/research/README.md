# Windows adaptation research records

These records were gathered for
[milestone 20](https://github.com/aigengame/godot-agent/milestone/20) and
[#1109](https://github.com/aigengame/godot-agent/issues/1109). They are evidence
and publication snapshots, not extra live sources of architectural decisions.

- [Windows audit](windows-platform-audit-2026-10-06.md): command inventory,
  native full e2e results and diagnostic reruns at `6d5da3df`.
- [Planning record](windows-adaptation-plan-2026-10-06.md) and
  [isolated probes](windows-adaptation-plan-2026-10-06/): feasibility and limits,
  not product Live acceptance.
- [Published task index](windows-adaptation-tickets-2026-10-06/README.md): initial
  issue bodies, identifiers and read-back verification of membership/dependencies.
- [GitHub relationship research](github-issue-hierarchy-and-dependencies-2026-10-06.md):
  rationale for one parent level plus explicit blocked-by edges.

[ADR-0046](../adr/0046-windows-live-uses-local-tcp-and-owned-session-adapters.md)
owns the accepted architecture; the [development guide](../windows-platform-development.md)
owns the integration workflow. Tracker issues own current acceptance and status.

Raw reports retain their original counts, output and machine paths. Probe scripts
are historical source snapshots, including pre-layering import names and local
setup paths. Their `.py.txt` archive suffix preserves the original bytes without
registering historical probes as executable Python tooling subject to today's
formatting gate. To repeat a probe on a later revision, copy it to task-local scratch,
update imports/setup in that copy and save a separately labeled result. Do not
rewrite the original evidence to suggest it was run after layering. These scripts
are not supported package tooling or production defaults.

Local Git attributes disable newline conversion for historical evidence. Raw
reports, structured results and probe snapshots keep their original bytes and are shown as data additions rather
than normalized line patches; inspect the files or their raw blob when needed.
This does not change formatting rules for prose, package code or tests.
