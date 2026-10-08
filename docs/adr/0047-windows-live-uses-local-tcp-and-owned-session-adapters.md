---
status: accepted
---

# Windows Live uses local TCP and owned-session adapters within the existing layers

The Windows audit found that the entire Live stack depends on Unix sockets,
locks and process groups. The user accepted the incremental design in
[#1109](https://github.com/aigengame/godot-agent/issues/1109). Windows therefore
gets local transport, discovery and lifetime adapters; Unix retains its current
implementations. Reusing the existing framing and operations keeps the change
at the actual platform boundaries instead of rebuilding the core.

Accepted on 2026-10-06 as the target architecture for
[milestone 20](https://github.com/aigengame/godot-agent/milestone/20). **Acceptance
of this decision is not delivery of Windows Live.** The current implementation
still rejects Windows Live. Each implementation issue opens only its verified
surface; [#1124](https://github.com/aigengame/godot-agent/issues/1124) owns final
parity acceptance. This ADR amends ADR-0021's Unix-only transport scope and
ADR-0017's Windows lifetime mechanism, not their other contracts.

## Decisions

### Transport and discovery remain per project

Both Windows IPC legs use stream TCP on literal `127.0.0.1`. Bind two listeners
with port `0`, retain the bound sockets and publish their actual addresses only
after successful setup. The CLI connects through private discovery; the harness
is told its endpoint at launch. Neither scans for ports. macOS/Linux retain UDS
on both legs, their short runtime paths and flock-based discovery.

The existing canonical project identity remains the discovery key. Windows uses
a dedicated private runtime directory under `LOCALAPPDATA`; if it is absent,
use a resolved current-user home fallback. Refuse setup if a private usable root
cannot be established. This adds no new global registry or project resolver.

A Windows stable lock file is separate from readable endpoint metadata. A held
`msvcrt` byte-region lock excludes a second owner; the lock file is never unlinked
during lifetime or recovery. Acquire before publication or stale reclamation.
Atomically publish canonical project, daemon identity/generation, endpoints and
the private authentication secret. Validate identity and authenticate the
endpoint; a PID's existence alone does not establish ownership or liveness.
After retiring the owned session and closing listeners, remove only the owned
metadata and release the lock last. A losing start must not replace the winner's
record or remove its installation.

Create a new private runtime directory with Python 3.13's Windows
`os.mkdir(mode=0o700)` behavior. Existing directories require a narrow permission
check or rejection; Windows `chmod(0700)` does not establish the contract. The
owner, SYSTEM and administrators are within that local access boundary. Do not
build a general ACL policy engine or silently adopt a shared unsafe directory.
Exact layout and validation are owned by
[#1117](https://github.com/aigengame/godot-agent/issues/1117).

### Authentication and deadlines preserve the existing isolation contract

Authenticate Windows CLI/control connections before accepting live, status or
stop requests. A fixed-size private secret frame precedes the existing request;
secrets never enter public models, schema or normal logs. Keep the harness's
launch token and scene verification. A wrong peer is dropped and the next
eligible harness connection may be accepted within the original launch deadline.

Unauthenticated, malformed and trickling connections cannot hold the serial
daemon indefinitely. Recompute remaining time against an absolute deadline at
each bounded read; do not restart the clock for a new phase or rejected peer.
This retains ADR-0017's waiting/commit budget rather than promising a new hard
wall-clock cancellation mechanism. Trusted-project and same-user trust remain
as in ADR-0009/0018; this is not a remote-access or security-platform design.

### Harness adaptation keeps handlers and state consistency

Use `StreamPeerSocket` for the common peer interface, with UDS on Unix and TCP on
Windows. TCP connection readiness is asynchronous: send the token only after
the connection is ready. Keep partial bytes until a complete length prefix and
body are available; dispatch through the existing handlers only then. A partial
request must not block the game's main thread.

Preserve existing framing, sentinel/result shapes, `EngineSession.request`, one
pending operation, single-writer serialization, frame coherence, scene
verification and session identity. Verify large replies and disconnect behavior
before adding any send queue. No per-operation Windows copies or new RPC stack.

### Windows owns the Engine session tree

Unix retains its captured POSIX process group and accepted residual numeric-id
reuse race from ADR-0017. Windows uses a Job Object for the processes owned by
the daemon's Engine session. Ownership must be established before the engine
can create descendants; closing the owning Job must retire them even after
the leader exits or the daemon crashes. Keep durable handles until retirement.
This decision applies to Live session ownership, not all Headless launches.

The first implementation candidate is a private worker that waits at a startup
gate, is assigned to the Job and then launches Godot. A narrower suspended-spawn
adapter is acceptable if it proves simpler. The worker is not a new service or
public process-management API. Its actual Godot spawn outcome, launch exception
and full Windows exit status must reach existing callers within the original
deadline; worker startup must not conceal an engine startup failure as a
harness-connect timeout. Preserve normal poll/wait behavior. Do not depend on
private `Popen` handles, process-name kills or PID scans.

[#1118](https://github.com/aigengame/godot-agent/issues/1118) must verify the real
GUI/console Godot topology, stop, timeout, restart, daemon crash, leader-exited
cleanup and unrelated-process preservation. CLI exit and parent terminal/IDE
closure are separate daemon-detachment tests in #1117; a process group flag alone
does not prove detachment from a host Job. Disclose any host limitation.
Windows forced retirement does not promise Unix SIGTERM's exit-flush semantics;
retain available diagnostics without adding a fresh grace budget.

### Public endpoints and availability have one authority

The public `daemon start/status` result keeps `socket_path` as a real Unix path
and permits null on Windows. Add one optional typed `Daemon endpoint` with only
transport/address, never a secret, TCP URI stuffed into a path, or metadata path
masquerading as a socket. The command surface owns this DTO and conversion;
core contracts do not import daemon-internal endpoint types. Models, schema and
human renderers change together in #1117.

The existing `live_stack_constraints` remains the sole static support authority.
It does not inspect discovery, locks or runtime endpoints. A temporary Windows
operation allow-list there can expose verified increments; runtime guards,
schema, help and the bundled skill follow it. Install/uninstall may arrive
before daemon lifecycle; a running daemon does not claim an Engine session is
ready. Before rendered acceptance, Windows windowed requests fail explicitly.
If partial-release packaging is disproportionate, keep the additions behind
the existing gate until full acceptance rather than create another feature
system. Remove transitional gating when #1124 passes.

Headless remains Godot 4.4+ and Live remains 4.6+. TCP on older engines does not
justify an older-engine compatibility project.

## Boundaries and rejected alternatives

- ADR-0045 remains binding. Transport, discovery/lock, Job ownership and display
  adaptation belong to daemon. Core stays closed, framework-free and without
  process entries. Keep the current import-direction gate, runner seams, failure
  classification, Value projection and completed-run settlement. No upward
  imports, utility package, façade, old-path shim or Windows dispatch.
- Native named pipes would require another harness transport implementation;
  TCP is already available in Godot and reuses Python's stream framing. Replacing
  Unix UDS with TCP would enlarge the change without closing another known gap.
- Public CLI/MCP stdio uses UTF-8 at entry, with explicit relevant I/O encodings.
  Fix the contract at its source; do not add code-page/CJK conversion, guessing,
  lossy fallback or `chcp` setup. MCP remains on the public CLI ABI; a few stdlib
  entry calls do not warrant a shared infrastructure layer.
- Godot resolution uses only `--godot`, then `GDA_GODOT`, on Windows, macOS and
  Linux. This replaces the original PATH/fallback clause with
  [#1130](https://github.com/aigengame/godot-agent/issues/1130), delivered by
  [PR #1132](https://github.com/aigengame/godot-agent/pull/1132). With no engine
  configured, engine operations return `binary_not_found` before launch and name
  both settings; version provenance reports `godot.binary=null`. No automatic
  Godot PATH discovery or platform default is added. The independent MCP
  `GDA_BIN` command override gets native Windows argv parsing; its default remains
  `[sys.executable, -m, gda]`. No gda PATH discovery or second project authority.
- Windows CI, remote IPC/TLS, endpoint scanning, platform/provider registries,
  general process/ACL/observability frameworks, packaging/installer systems and
  broad core rewrites are excluded. Native export/smoke reuses the existing
  completed-run step; windowed preflight is a narrow daemon display adapter.

## Evidence and remaining work

### Inert harness lifecycle (#1116)

Windows `daemon install` and `daemon uninstall` reuse the existing installer,
transactional rollback and paired removal. The static `live_stack_constraints`
authority allows only these two operations; their schema has no engine floor.
Runtime lifecycle guards read the same authority. No transport or session is
opened by this slice. Unix running-daemon refusal remains in place. Windows
uninstall does not consult Unix UDS/flock discovery while native daemon startup
is unsupported; #1117 must wire its native liveness guard before opening startup.
The following increment opens daemon lifecycle; Engine-session operations remain
explicit refusals.

### Authenticated daemon lifecycle (#1117)

The daemon retains both port-0 loopback listeners before publishing private JSON
metadata beside a separate stable `.lock`. Metadata records the daemon's own PID,
canonical project, both ports and a fresh 32-byte secret. The `.lock` first byte
is held with `msvcrt` until listeners are closed and metadata is removed; it is
never unlinked. A losing daemon does not enter the winner's cleanup path.
Windows start/install/uninstall commands serialize harness transactions on the
second byte of that same file. Start holds it from the current-state check through
installation, readiness or rollback, so another pending start cannot adopt an
installation that its first caller can still undo. The daemon holds only the
first byte; it does not wait on its parent's transaction lock.
Failed CLI startup acquires the ownership byte before restoring its harness
snapshot; if another owner holds the slot, it retains the install and reports
the incomplete rollback instead of removing the winner's files. A spawned child
checks the parent's original readiness deadline after acquiring ownership and
before publication. An expired child closes only its lock, leaving stale metadata
untouched; it cannot publish after the parent has restored the installation.
If startup is interrupted or readiness raises after a successful spawn, rollback
retains the free ownership byte until the original deadline before restoring.
This consumes the remaining startup budget, without starting another one.

The Windows adapter creates the private runtime with mode 0o700 and reads native
ownership/DACL to reject existing shared or reparse paths. It does not change
existing ACLs. SYSTEM/Administrators and current-user/OWNER RIGHTS entries remain
within the chosen boundary. Metadata publication uses a same-directory temporary
file and atomic replacement; the secret stays out of public endpoint DTOs.

Each TCP control connection sends the fixed-size secret before the existing JSON
frame. Authentication and request reads share the existing two-second absolute
control deadline; wrong, silent, malformed and trickling peers are dropped.
Windows status and repeated start require an authenticated reply with the
discovered PID before reporting a running owner. Uninstall also protects an
occupied ownership byte when metadata is absent or authentication fails. Windows stop
requires an authenticated acknowledgement and retirement, without PID-based
termination. Unix UDS/flock and session behavior remain unchanged.

Windows spawning uses Python subprocess detached/new-process-group/breakaway
flags with closed standard streams. A host Job must allow breakaway; a refused
spawn reports failure and uses the existing harness rollback transaction.
The public endpoint is TCP transport/address; `socket_path` stays a Unix path
and is null on Windows. A running daemon is not a ready Engine session:
Windows windowed startup and direct/CLI/MCP engine-session calls remain gated
until #1118 and the rendered increments pass acceptance.
The temporary lifecycle allow-list applies only to lifecycle recipe descriptors,
not to LIVE wire operation names; an authenticated peer cannot use a lifecycle
name to bypass the session refusal.

The [audit](../research/windows-platform-audit-2026-10-06.md) at `6d5da3df` records
859 selected e2e cases: 655 passed, 48 failed, 32 setup errors and 124 skipped.
The [bounded probes](../research/windows-adaptation-plan-2026-10-06/README.md) establish
TCP handler reuse and nonblocking fragmented receive, private-directory
inheritance, separate lock exclusion and controlled nested-Job cleanup. They do
not establish product Live, actual engine Job topology, network-share runtime or
desktop parity. Historical probe imports remain tied to their source revision.

The [development guide](../windows-platform-development.md) routes the eight
increments to their fifteen issues and records branch/verification gates.
Implementation PRs must attach current-revision real public-channel evidence and
relevant actual Unix regressions; a subset rerun or mocked seam does not establish
full parity. Existing unverified scan cost/cache questions (#1077) remain separate.

Primary references: [Python 3.13 private mkdir](https://docs.python.org/3.13/library/os.html#os.mkdir),
[byte-region locking](https://docs.python.org/3.13/library/msvcrt.html#msvcrt.locking),
[native file URIs](https://docs.python.org/3.13/library/pathlib.html#pathlib.Path.from_uri),
[Godot StreamPeerSocket](https://docs.godotengine.org/en/4.6/classes/class_streampeersocket.html),
[TCP](https://docs.godotengine.org/en/4.6/classes/class_streampeertcp.html),
[partial reads](https://docs.godotengine.org/en/4.6/classes/class_streampeer.html),
and [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
