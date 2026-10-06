# Published Windows adaptation tickets

Implementation base: `7e23ba2d819b69159f055bfca9d0a2cbd74bf923` (core layering merged through #1108).

[Milestone](https://github.com/aigengame/godot-agent/milestone/20) — Close Windows Platform Capability Gaps and Strengthen Cross-Platform Adaptability

[Overall design](https://github.com/aigengame/godot-agent/issues/1109)

The overall tracker design owns scope; each implementation issue owns delivery acceptance. Local bodies are publication snapshots, not an independently edited authority. All issues have ready-for-agent and the milestone. One native parent level provides scope/navigation/progress; only explicit blocked-by links define ordering. The overall goal is blocked by final integration #1124. Research: [hierarchy and dependencies](../github-issue-hierarchy-and-dependencies-2026-10-06.md).

| Task | Issue | Blocked by |
| --- | --- | --- |
| T01 | [gda Windows: make CLI and MCP stdio UTF-8 at the entry points](https://github.com/aigengame/godot-agent/issues/1110) | None |
| T02 | [gda-mcp Windows: route drive and UNC roots to the intended project](https://github.com/aigengame/godot-agent/issues/1111) | [#1110](https://github.com/aigengame/godot-agent/issues/1110) |
| T03 | [gda Windows: resolve native Godot and preserve MCP command argv](https://github.com/aigengame/godot-agent/issues/1112) | [#1110](https://github.com/aigengame/godot-agent/issues/1110) |
| T04 | [gda tests: make local Windows e2e fixtures and assertions portable](https://github.com/aigengame/godot-agent/issues/1113) | None |
| T05 | [gda Windows: recognize native exception exits without changing ordinary verdicts](https://github.com/aigengame/godot-agent/issues/1114) | None |
| T06 | [gda Windows: export and smoke-test a Windows Desktop artifact](https://github.com/aigengame/godot-agent/issues/1115) | [#1110](https://github.com/aigengame/godot-agent/issues/1110), [#1113](https://github.com/aigengame/godot-agent/issues/1113) |
| T07 | [gda Windows: install and remove the inert project harness](https://github.com/aigengame/godot-agent/issues/1116) | [#1110](https://github.com/aigengame/godot-agent/issues/1110) |
| T08 | [gda Windows: start, discover and stop an authenticated project daemon](https://github.com/aigengame/godot-agent/issues/1117) | [#1116](https://github.com/aigengame/godot-agent/issues/1116) |
| T09 | [gda Windows: complete a headless Live session from readiness to retirement](https://github.com/aigengame/godot-agent/issues/1118) | [#1117](https://github.com/aigengame/godot-agent/issues/1117) |
| T10 | [gda Windows Live: complete runtime game inspection and mutation](https://github.com/aigengame/godot-agent/issues/1119) | [#1118](https://github.com/aigengame/godot-agent/issues/1118) |
| T11 | [gda Windows Live: deliver both input routes and bounded sequences](https://github.com/aigengame/godot-agent/issues/1120) | [#1118](https://github.com/aigengame/godot-agent/issues/1118) |
| T12 | [gda Windows Live: complete performance, diagnostics and logger observations](https://github.com/aigengame/godot-agent/issues/1121) | [#1118](https://github.com/aigengame/godot-agent/issues/1118) |
| T13 | [gda Windows Live: launch a windowed session and capture rendered frames](https://github.com/aigengame/godot-agent/issues/1122) | [#1118](https://github.com/aigengame/godot-agent/issues/1118) |
| T14 | [gda Windows Live: verify input-driven UI effects in rendered sessions](https://github.com/aigengame/godot-agent/issues/1123) | [#1120](https://github.com/aigengame/godot-agent/issues/1120), [#1122](https://github.com/aigengame/godot-agent/issues/1122) |
| T15 | [gda Windows: verify full parity and synchronize platform guidance](https://github.com/aigengame/godot-agent/issues/1124) | [#1111](https://github.com/aigengame/godot-agent/issues/1111), [#1112](https://github.com/aigengame/godot-agent/issues/1112), [#1114](https://github.com/aigengame/godot-agent/issues/1114), [#1115](https://github.com/aigengame/godot-agent/issues/1115), [#1119](https://github.com/aigengame/godot-agent/issues/1119), [#1121](https://github.com/aigengame/godot-agent/issues/1121), [#1123](https://github.com/aigengame/godot-agent/issues/1123) |

Verified by reading back all bodies, labels, milestone membership, fifteen native parent links and twenty-one explicit blocking edges (twenty implementation edges plus the overall completion edge). No product/test code changed; no issue outside this newly created set was closed or edited.
