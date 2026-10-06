## Goal and decision authority

Close Windows Platform Capability Gaps and Strengthen Cross-Platform Adaptability. The user accepted the design and eight increments on 2026-10-06 and authorized this tracker delivery. This issue is the goal/design authority; implementation issues own their acceptance. Keep this issue open until final integration is complete. Use one native parent/sub-issue level for scope/navigation/progress and explicit blocked-by dependencies for execution/completion order. Sharing a parent creates no implied dependency; progress counts do not replace acceptance evidence. The user authorized this combined configuration after research confirmed its distinct benefits.

Core layering is merged via #1108. Implementation base: `7e23ba2d819b69159f055bfca9d0a2cbd74bf923`. Historical audit base: `6d5da3df36d7bf3ba6972c485ef955a2bf8c1926`; relocations do not establish new Windows capability evidence.

## Audit and bounded experiments

859 e2e cases selected: 655 passed, 48 failed, 32 setup errors, 124 skipped. UTF-8 retry of the 80 failures/errors: 19 passed, 28 failed, 32 errors, one skipped. This subset is not a green full suite. Eleven engine-verdict observations were not reproduced and have no established cause. Of 80 public commands, 24 exclude Windows; the other 56 are not all verified merely because no exclusion exists.

Confirmed gaps: Unix-only Live sockets/locks/process groups; native executable resolution; stdio encoding; drive/UNC MCP roots; GDA_BIN backslash loss; unsigned native exception status; permissive display stub; Unix/macOS-oriented fixtures and native smoke selection.

Windows 11/Python 3.13.7/Godot 4.6.3 feasibility probes passed native drive/UNC URI parsing, separate lock exclusion/readable metadata/owner-exit release, mode-0o700 directory ACL inheritance and nested Job cleanup for running/exited controlled leaders. A copied full harness with connection/receive adaptation completed TCP token/scene verification, tree/get/set and 16 monitors; a 400ms partial-body pause still allowed 25 game ticks. These are isolated probes, not product CLI/daemon e2e. Mounted-share runtime, actual Godot Job topology and parent-host closure remain unverified. Historical raw results/scripts remain in the initiating workspace; implementation PRs must preserve new reproducible evidence at their revisions.

## Architecture

- Preserve Unix UDS/flock. Windows uses literal 127.0.0.1, two retained port-0 listeners, private atomic endpoint metadata and authentication. Reuse framing, recipes and handlers. No fixed port or free-port-then-close race.
- A stable separate Windows lock protects publication/recovery. Never unlink it; acquire first, retire owned session/remove metadata, release last. PID presence alone is not ownership. New private runtime creation uses standard-library mode 0o700; existing directories get a narrow check/rejection, not an ACL framework.
- Authenticate control/live peers before operations; keep token/scene handshake, reject wrong peers and bound silent/malformed reads by the original absolute deadline. Secrets never enter public models/schema/logs.
- Harness adaptation is peer creation, asynchronous TCP readiness and complete-frame buffering through StreamPeerSocket. Preserve one writer and frame-coherent dispatch. Verify large replies/disconnect before adding send queues; no generic RPC rewrite.
- Windows Job ownership starts before engine descendants. Verify the small controlled worker gate first or a narrower suspended-spawn alternative. Preserve actual engine launch exceptions/full exit status and poll/wait within the original budget; worker startup is not engine startup. Keep handles after leader exit until retirement. Verify stop/crash/timeout cleanup and parent-terminal detachment separately, without process-name/PID scans or private Popen handles.
- Keep Unix socket_path and make it nullable on Windows; add one optional typed public transport/address endpoint with no secret. DTO conversion belongs to the command surface; core never imports daemon endpoint types.
- Establish UTF-8 before CLI/MCP parsing/emission, with a console wrapper and small equivalent MCP stdlib setup rather than global utility infrastructure. Preserve opaque bytes/CRLF. Godot resolution is --godot > GDA_GODOT > bounded PATH > applicable fallback; the independent MCP GDA_BIN command override uses native argv parsing and defaults to [sys.executable, -m, gda], never a gda PATH lookup. Native file URI parsing addresses actual roots defects. Headless stays 4.4+, Live stays 4.6+.

## Core layering and support rollout

ADR-0045 remains binding: `exit_codes < core.project < core.engine < core.contract < core.failure < core.steps < daemon < harness < surface < commands < cli`.

Transport, Windows discovery/lock, owned Job and display probe stay in daemon. Core is closed/framework-free/process-entry-free. No upward imports, root/core utilities, old-path shims or Windows dispatch copies. MCP remains on the public CLI ABI. Preserve RunResult, GodotRunner, EngineSession.request, Value and settle_completed_run; smoke must reuse the completed-run step. Run the current import-direction gate in each slice without weakening it.

live_stack_constraints remains the single static support authority, not a reader of runtime metadata. Partial release uses one temporary allow-list there with matching runtime guards/schema/help; unverified windowed calls fail explicitly. If partial packaging costs too much, keep implementation behind the current gate until complete rather than add a second feature system.

## Incremental tasks

The approved eight increments become these bounded, independently verifiable tasks. Dependencies describe real gates; suggested order does not add artificial edges.

1. T01 — UTF-8 public entries. Blocked by: none. Delivers native CLI/MCP round-trip.
2. T02 — MCP roots. Blocked by: T01. Delivers correct advertised-project routing.
3. T03 — executable/argv resolution. Blocked by: T01. Delivers configured native launch and a real MCP override path.
4. T04 — portable local fixtures. Blocked by: none. Delivers trustworthy test execution.
5. T05 — native exception verdict. Blocked by: none. Delivers accurate abnormal status classification.
6. T06 — native export/smoke. Blocked by: T01, T04. Delivers a real exported artifact path.
7. T07 — inert install/uninstall. Blocked by: T01. Delivers the filesystem lifecycle slice.
8. T08 — authenticated daemon lifecycle. Blocked by: T07. Delivers start/status/stop and discovery.
9. T09 — first owned headless session. Blocked by: T08. Delivers readiness/tree/get/retirement.
10. T10 — runtime game group. Blocked by: T09. Delivers complete inspection/mutation.
11. T11 — input routes/sequences. Blocked by: T09. Delivers observed headless input effects.
12. T12 — performance/diag/logger. Blocked by: T09. Delivers real observations.
13. T13 — rendered capture. Blocked by: T09. Delivers desktop preflight and actual pixels.
14. T14 — rendered input effects. Blocked by: T11, T13. Delivers observed UI changes.
15. T15 — final parity/guidance. Blocked by: T02, T03, T05, T06, T10, T12, T14 (T04 is transitive via T06). Delivers final evidence and synchronized support.

Mapping to approved stages: 1=T01; 2=T02/T03; 3=T04/T05; 4=T06; 5=T07/T08; 6=T09; 7=T10/T11/T12; 8=T13/T14/T15. No wide prefactor is required after layering. Each slice carries its relevant docs/schema/config/tests.

## Scope exclusions

Windows CI is excluded. No code-page/CJK conversion/guessing, chcp setup, generic platform/provider registry, container, remote IPC/TLS/scan, packaging/installer framework, process-manager/observability platform or broad core rewrite. Authentication/private discovery/Job lifetime preserve existing contracts and do not authorize platformization. No Windows operation copies. Existing project-scan cost/cache questions (#1077) stay separate.

## Completion criteria

- [ ] All 24 original excluded commands have real Windows evidence: daemon lifecycle/readiness (6), game (6), input (6), perf (2), diag (1), logger (1), screen (2).
- [ ] Native CLI/MCP UTF-8, correct roots/argv, native export/smoke, inert harness, owned-tree retirement and rendered capture/input are verified through public channels.
- [ ] Full local Windows e2e selection covers headless, Live, rendered and native export/smoke; counts/warnings/reasons/raw results distinguish new cases and genuine prerequisites without hiding supported failures or selecting only passing subsets.
- [ ] Actual relevant macOS/Linux regression evidence precedes a three-platform claim; absent host access stays an incomplete gate.
- [ ] README translations and synchronization markers, catalog, registration examples, bundled skill and public companion guide, help/schema/version floors and narrow transport/lifetime ADR amendments agree with shipped behavior; transitional gates are removed after acceptance.
- [ ] Existing layering and required checks remain intact; no Windows CI or excluded platformization is added.

## Blocked by

- #1124 — final integration and parity acceptance. The accepted design itself does not block implementation; this edge expresses completion of the overall goal, not a new design approval gate.

## Decision references

ADR-0017 (Engine session lifetime), ADR-0018 (inertness), ADR-0020 (State consistency), ADR-0021 (transport/discovery/floor), ADR-0028 (export cleanliness), ADR-0045 (layering) and merged PR #1108. Record narrow Windows amendments during implementation rather than silently reinterpret the existing decisions.
