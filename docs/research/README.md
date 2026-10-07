# Windows audit and feasibility evidence

- [Audit](windows-platform-audit-2026-10-06.md): command inventory, native full
  e2e baseline, diagnostic reruns and their raw JUnit/log/classification records.
- [Feasibility probes](windows-adaptation-plan-2026-10-06/README.md): TCP, lock,
  ACL and controlled Job evidence, with scripts, results and verification limits.

These historical records remain frozen at their stated revisions; later runs
produce separate evidence. Local Git attributes preserve original evidence bytes.
They do not freeze an extra copy of the implementation plan or tracker.

[ADR-0046](../adr/0046-windows-live-uses-local-tcp-and-owned-session-adapters.md)
owns architecture; [#1109](https://github.com/aigengame/godot-agent/issues/1109)
and [milestone 20](https://github.com/aigengame/godot-agent/milestone/20)
own scope and acceptance; the [development guide](../windows-platform-development.md)
owns delivery order and branch rules. Historical audit follow-up suggestions are
not current scope: Windows CI remains excluded.
