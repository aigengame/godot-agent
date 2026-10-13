# Windows audit and feasibility evidence

- [Audit](windows-platform-audit-2026-10-06.md): command inventory, native full
  e2e baseline and diagnostic reruns.
- [Feasibility probes](windows-adaptation-plan-2026-10-06/README.md): TCP, lock,
  ACL and controlled Job evidence, with verification limits.

These two records are the evidence
[ADR-0047](../adr/0047-windows-live-uses-local-tcp-and-owned-session-adapters.md)
cites. They remain frozen at their stated revisions; later runs produce separate
evidence. The raw result files that the records name (JUnit reports, logs, JSON
results, compressed extracts and probe-script copies) are not in the repository;
they stay in the workspace that produced them. The records of #1110, #1111,
#1113, #1136 and #1137 were removed on 2026-10-13, after milestone 20 closed;
the last commit that holds them is `3460ca2ed`.

ADR-0047 owns architecture; [#1109](https://github.com/aigengame/godot-agent/issues/1109)
and [milestone 20](https://github.com/aigengame/godot-agent/milestone/20), both
closed on 2026-10-13, owned scope and acceptance; the
[development guide](../windows-platform-development.md) owns delivery order and
branch rules. Historical audit follow-up suggestions are not current scope:
Windows CI remains excluded.
