# Windows audit and feasibility evidence

- [Audit](windows-platform-audit-2026-10-06.md): command inventory, native full
  e2e baseline and diagnostic reruns.
- [Feasibility probes](windows-adaptation-plan-2026-10-06/README.md): TCP, lock,
  ACL and controlled Job evidence, with verification limits.
- [UTF-8 entry verification](windows-utf8-entry-2026-10-07/README.md): #1110's
  native Windows CLI/MCP round trips and byte-preserving spill result.
- [MCP file-root verification](windows-mcp-roots-2026-10-07/README.md): #1111's
  real Windows stdio project selection, UNC parser boundary and baseline control.
- [Fixture verification](windows-e2e-fixtures-2026-10-07/README.md): #1113's
  native Windows e2e run after the fixture repairs, with the integration-base run.
- [Native operation diagnosis](windows-native-operation-diagnosis-2026-10-08/README.md):
  #1136's bounded diagnosis of two native `0xC0000005` exits.

These historical records remain frozen at their stated revisions; later runs
produce separate evidence. The raw result files that the records name (JUnit
reports, logs, JSON results, compressed extracts and probe-script copies) are not
in the repository; they stay in the workspace that produced them. The records do
not freeze an extra copy of the implementation plan or tracker.

[ADR-0047](../adr/0047-windows-live-uses-local-tcp-and-owned-session-adapters.md)
owns architecture; [#1109](https://github.com/aigengame/godot-agent/issues/1109)
and [milestone 20](https://github.com/aigengame/godot-agent/milestone/20)
own scope and acceptance; the [development guide](../windows-platform-development.md)
owns delivery order and branch rules. Historical audit follow-up suggestions are
not current scope: Windows CI remains excluded.
