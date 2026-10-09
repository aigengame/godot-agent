# Windows platform development: milestone 20

This guide records how the accepted Windows design is delivered. It is not an
installation guide or a claim that Windows Live already works.

## Authorities and baseline

- [#1109](https://github.com/aigengame/godot-agent/issues/1109) owns the goal,
  scope and overall acceptance. The implementation issues own their individual
  acceptance; keep #1109 open until #1124 completes.
- [ADR-0047](adr/0047-windows-live-uses-local-tcp-and-owned-session-adapters.md)
  owns architectural decisions; [ADR-0045](adr/0045-python-core-splits-into-functional-packages-in-import-order.md)
  owns package boundaries. [CONTEXT](../CONTEXT.md) is the domain glossary.
- The [audit](research/windows-platform-audit-2026-10-06.md) and
  [feasibility probes](research/windows-adaptation-plan-2026-10-06/README.md) are
  frozen facts at their recorded revisions, not another plan or support claim.
  Tracker issues own current acceptance and dependencies; do not keep competing
  local copies of their bodies.

The integration branch starts at main
`7e23ba2d819b69159f055bfca9d0a2cbd74bf923`, which merged core layering through
#1108. Audit/prototype imports at `6d5da3df` are historical; an implementation
must use the current module homes. Do not add old-path shims to run a probe.

## Branch and review flow

The milestone integration branch is
[`codex/windows-platform-dev`](https://github.com/aigengame/godot-agent/tree/codex/windows-platform-dev).
The first documentation branch is `codex/1109-windows-design`, cut from that
integration branch. Feature/documentation PRs target the integration branch;
promotion to main follows final acceptance, not the first passing slice.

For each task, update the integration checkout and cut an issue branch from it.
Use a separate worktree if concurrent work is needed. Reconcile shared predicate
edits rather than maintaining competing platform capability lists. Review and
integrate small PRs in the actual blocked-by order; do not merge directly to
main as a shortcut around the integration evidence.

Parent/sub-issue links express membership/navigation/progress. Only explicit
blocked-by links express prerequisites. The twenty implementation dependencies
plus #1109 waiting for #1124 form the completion graph. The initial unblocked
frontier is #1110, #1113 and #1114. This is the recorded initial graph; read the
tracker for current completion state.

The documentation PR uses `Refs #1109`, not `Closes #1109`. It records decisions
and evidence, leaving implementation and final verification to their issues.

## Incremental delivery

| Accepted increment | Issues | Completion path |
| --- | --- | --- |
| 1. UTF-8 entry contract | [#1110](https://github.com/aigengame/godot-agent/issues/1110) | Native CLI/MCP startup and Unicode round-trip without environment workarounds |
| 2. Paths and launch configuration | [#1111](https://github.com/aigengame/godot-agent/issues/1111), [#1112](https://github.com/aigengame/godot-agent/issues/1112) | Correct MCP root and native Godot/MCP argv configuration |
| 3. Trustworthy local tests/verdicts | [#1113](https://github.com/aigengame/godot-agent/issues/1113), [#1114](https://github.com/aigengame/godot-agent/issues/1114) | Portable fixtures and known native-exception classification |
| 4. Native export/smoke | [#1115](https://github.com/aigengame/godot-agent/issues/1115) | Real Windows Desktop export and isolated artifact smoke |
| 5. Harness and daemon lifecycle | [#1116](https://github.com/aigengame/godot-agent/issues/1116), [#1117](https://github.com/aigengame/godot-agent/issues/1117) | Inert install/uninstall, then authenticated start/status/stop |
| 6. First owned headless session | [#1118](https://github.com/aigengame/godot-agent/issues/1118) | wait-ready, tree/get and complete retirement through CLI/MCP |
| 7. Non-rendered Live | [#1119](https://github.com/aigengame/godot-agent/issues/1119), [#1120](https://github.com/aigengame/godot-agent/issues/1120), [#1121](https://github.com/aigengame/godot-agent/issues/1121) | Game state, both input routes and perf/diag/logger observations |
| 8. Rendered parity and final evidence | [#1122](https://github.com/aigengame/godot-agent/issues/1122), [#1123](https://github.com/aigengame/godot-agent/issues/1123), [#1124](https://github.com/aigengame/godot-agent/issues/1124) | Actual capture/UI effects, full selection and synchronized guidance |

The numbers suggest easy-to-hard work, not artificial dependencies. Documentation,
configuration, schema and relevant tests travel with each behavior. A transport
probe alone never closes an operation issue.

## Inert harness slice (#1116)

Windows supports `gda daemon install` and `gda daemon uninstall` without a daemon
or engine launch. They use the existing installer, rollback transaction and
paired removal. Inspect the JSON mutation receipt and project changes; a repeat
install of the current harness writes nothing. Plain game and editor runs keep
the harness inert. This slice alone does not establish daemon readiness or Live
support; those arrive through #1117 and #1118.

## Authenticated daemon lifecycle (#1117)

Windows start/status/stop use private per-project discovery under LOCALAPPDATA,
authenticated loopback TCP and a stable separate lock. Both listeners remain
bound before endpoint metadata is published. A running daemon protects its
harness from uninstall; stop permits ordinary and idempotent removal.
`socket_path` is null for TCP, and the optional public `endpoint` contains only
transport/address. An idle daemon has no session identity or startup verdict.

Startup detaches from the console and parent Job; a host that prohibits Job
breakaway receives a failed-start refusal with installation rollback. Running
means the daemon serves control requests, not that an Engine session is ready.
Windowed startup remains refused. The first headless Engine-session routes are
described below. See
[ADR-0047](adr/0047-windows-live-uses-local-tcp-and-owned-session-adapters.md).

## First headless Engine session (#1118)

Windows `daemon wait-ready`, `game tree` and `game get` now use the existing
recipes and handlers through authenticated TCP. Other Live routes remain gated
until their acceptance increments. Use the configured Godot 4.6+ console binary;
no additional transport or worker configuration is required.

The session owns a private Job before Godot can create descendants. Stop,
failed readiness, replacement and daemon crash retire the complete owned tree,
including descendants of an exited leader. Retirement is forced: game shutdown
callbacks and final buffered Session-log output may not run or flush. The
existing single launch deadline covers the worker gate, actual spawn, handshake
and failed-launch retirement. No Windows grace period is added.

Real CLI/MCP and protocol checks live in `test_e2e_windows_live_session.py`
(daemon and MCP) and `test_e2e_windows_harness_stream.py`. They cover both Godot
GUI/console paths, selected scenes, session identity, wrong peers, fragmented
input, large UTF-8 replies, disconnects and known owned descendants. Raw runs and
disposable native probes remain local; the PR records revision, commands and
counts. This increment does not establish desktop or complete Live parity.

## Current module boundaries

| Concern | Current owner |
| --- | --- |
| Godot resolution and Headless launch | `gda.core.engine.binary`, `launch`, `user_data`, `sentinel` |
| Static Live constraints | `gda.core.engine.execution.live_stack_constraints` |
| Project path authority | `gda.core.project.paths`; MCP retains its public-ABI context adapter |
| Error classification and shared settlement | `gda.core.failure.classify`, `gda.core.steps.completed_run` |
| Live client, display and new Windows leaves | `gda.daemon.client`, `display`, discovery/server/session and local adapters |
| Command schema/bindings/dispatch | `gda.surface`; lifecycle DTOs and renderers stay in their command group |
| Public process entries | CLI/module entry and MCP's own entry, outside core |

Core cannot import daemon/harness/surface/commands/CLI or CLI frameworks. Keep the
existing import-direction gate and package properties. Preserve runner seams,
RunResult, EngineSession.request, Value and operation handlers. Windows ownership
does not justify replacing all Headless launches. No shared utility/platform
layer is needed for a few entry calls or two known transport implementations.

## Local verification and reporting

Use the checkout's uv-managed interpreter, not an unrelated installed gda.
Select this host's engine explicitly; local drive/version paths are setup values,
never production defaults. Headless Godot remains 4.4+ and Live remains 4.6+.
Native export requires matching locally installed templates; rendered evidence
requires an actually usable desktop. Scope user-data relocation per invocation
and use per-run temporary directories. A suite-wide relocation can hide templates.

Godot configuration is `--godot` > `GDA_GODOT` on every platform, following
[#1130](https://github.com/aigengame/godot-agent/issues/1130). No automatic Godot
PATH discovery or built-in platform path is used.
[#1112](https://github.com/aigengame/godot-agent/issues/1112) verifies native
configuration and the independent MCP `GDA_BIN` argv contract using this rule.

Each behavioral slice needs its focused real CLI/MCP path, relevant contracts,
the existing import-direction gate and affected actual Unix regressions. Save
the exact revision, engine/interpreter/environment, command, selected/passed/
failed/setup-error/skipped counts, warnings, skip reasons and raw results. Keep
new cases separate from the original 859-case baseline. Do not hide encoding
defects with a suite-wide UTF-8 environment switch, normalize opaque byte evidence,
or turn a supported failure into a platform skip.

Full Windows selections at the headless, first-Live and final milestones cover
the applicable headless, Live, rendered and native export/smoke paths. Final
acceptance explicitly accounts for all original 24 excluded commands and actual
macOS/Linux regressions. Missing hosts or prerequisites are disclosed gaps, not
mocked replacements for a support claim. Eleven unreproduced audit observations
remain unexplained; capture raw evidence on recurrence instead of adding fallback
branches in advance.

Windows CI is excluded. Do not add a Windows workflow or make it a completion
prerequisite. Required checks remain the existing checks relevant to each PR.

For local Windows runs, use the per-test home/app-data, permission and link
fixtures in `tests.support`; do not mask them with an invocation-wide HOME or
USERPROFILE override. File-symlink privilege skips must name the missing
capability. The [#1113 verification receipt](research/windows-e2e-fixtures-2026-10-07/README.md)
records the native selection, its retained product failures and actual Linux
regressions. Native fast-tier portability remains a separately disclosed limit.
The [#1136 diagnostic receipt](research/windows-native-operation-diagnosis-2026-10-08/README.md)
routes captured native exception classification to #1114 and the unresolved
shared-fixture native fault to #1139. Passing sampled controls do not replace
the earlier failures or establish parity; #1124 retains these concerns.

## Decision versus implementation

This documentation slice accepts the design, adds the Daemon endpoint term,
records the transport/lifetime amendments and retains core audit/probe evidence.
It does not change production code, schemas, current platform gates,
human support tables or operation behavior.

The exact safe-existing-directory check, worker versus suspended-spawn topology,
desktop probe and partial-release packaging are verified in their owning slices.
Record evidence-driven narrow changes as ADR amendments when they change a
decision. Reopen scope with the user only for a material change, such as remote
access, a core dependency reversal, older Live engines or a platform framework.
