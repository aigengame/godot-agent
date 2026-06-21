---
status: accepted
---

# gda-daemon transport and discovery: Unix domain sockets end-to-end, per-project socket + pidfile discovery, and a Phase-2 live floor of Godot 4.6

ADR-0017 fixed [gda-daemon](../../CONTEXT.md)'s shape — a per-project supervisor + IPC
broker holding a transient [engine session](../../CONTEXT.md) with the
[gda harness](../../CONTEXT.md), routed by a static `kind` channel selector — but
**explicitly left three choices to the first implementation slice (#7)**: the
daemon's *transport*, its *discovery*, and the daemon↔harness *wire format*. PRD #6
records the same: "daemon transport / discovery — owned by the first slice #7." This
ADR fixes those three, and the one consequence they force: a **Phase-2 live version
floor**.

## Decision

**1. Transport is a Unix domain socket on both legs.** Both
`CLI → daemon` and `daemon → harness` are **UDS**, not TCP. The daemon (Python) listens
on `AF_UNIX` stream sockets; the harness (GDScript) connects back with
`StreamPeerUDS`. There is **no localhost TCP listener, no port, and no port scan** —
rejecting godot-mcp-pro's fixed `6505–6514` range probe. The daemon binds **two**
sockets per project: one the CLI clients connect to, and one the session's harness
connects back on; the harness socket path is handed to the engine session through the
launch marker (the args after `--`, ADR-0018), so the harness never discovers a port,
it is *told* a path.

**2. Discovery is per-project and deterministic.** The CLI and the lifecycle commands
locate the daemon by deriving the socket and **pidfile** paths from the **resolved
project root** (gda's existing `GDA_PROJECT → … → cwd` precedence, ADR-0006). To make
`daemon start`, `daemon status`, and a live command's attach all agree on the **same
daemon identity** regardless of how the project was referenced, the derivation is fixed
as a contract (the exact hash function is an implementation choice, the contract is not):

- **Canonicalize first.** The resolved project root is reduced to its canonical absolute
  path (symlinks resolved) before derivation, so two references to one project derive one
  identity and two different projects never collide.
- **Names are a stable hash of that canonical path.** Same canonical path → same socket
  and pidfile names; different paths → different names. The **pidfile records the
  canonical project path**, so a hash collision or a reused runtime slot is detectable:
  `status` / attach treat a pidfile whose recorded path ≠ the caller's resolved path as
  **foreign** (not this project's daemon), never as a hit.
- **Private, short runtime directory.** The socket and pidfile live in a per-user,
  owner-only (`0700`) runtime directory — `$XDG_RUNTIME_DIR` when set (Linux), else a
  `~/.gda/run`-style location — created with `0700` and the socket owner-only. This is
  what makes "no localhost surface" *also* "no other-user surface": the socket is never
  in a world-reachable directory. The directory must be **short**: a UDS path is bounded
  by the OS `sun_path` limit (104 bytes on macOS, 108 on Linux), never the long macOS
  `$TMPDIR`.
- **No resolved project is an error, not a global daemon.** The daemon is per-project by
  definition; when ADR-0006 resolves no project, `daemon start` / `status` and any live
  command return the structured project-resolution error (a project is required) rather
  than falling back to a default/global daemon.

Liveness is the pidfile (a held advisory lock = alive; a grabbable lock + present socket
= **stale**). `daemon start` reclaims a stale slot (unlink the socket, relaunch);
`daemon status` reports *not running* for a stale or foreign pidfile; a live command's
attach treats either as `daemon_not_running`. `gda daemon status` and the attach-or-fail
check (ADR-0017) both key on *socket present + pidfile alive + recorded path matches*.

**3. The wire format reuses the ADR-0002 sentinel result shape.** A live op's payload
crosses both legs as the **same** `<<<GDA:RESULT>>>…<<<GDA:END>>>` sentinel a headless
subprocess emits on stdout. The daemon relays the harness's sentinel string verbatim
into the `RunResult` the daemon IPC client returns, so `classify_run` / sentinel
parsing / output-model validation / `--json` / `GdaError` emission are **reused
unchanged** (ADR-0017). Request framing on each leg is a length-prefixed JSON
`{op, params}`; only the daemon-side framing is new code, the parser is not.

**4. Phase-2 live requires Godot ≥ 4.6 (amending ADR-0003).** `StreamPeerUDS` /
`UDSServer` landed in **Godot 4.6-stable** ("Core: Add UNIX domain socket support");
they do not exist in 4.4 / 4.5. Because the harness leg (decision 1) is UDS, the
engine session — hence **live operations** — needs **4.6+**. `gda daemon start`
**version-gates**: an engine below 4.6 returns the structured `version`-category error
ADR-0003 already defines for "too old," naming the floor. This amends ADR-0003 **for the
live layer only**: the **Phase-1 headless floor stays 4.4** (headless uses neither UDS
nor the daemon). 4.6 is already gda's development/test baseline, and live is a new
capability with no installed 4.4/4.5 live users to preserve.

## Considered options

- **Localhost TCP for the daemon↔harness leg (keep a 4.4 live floor).** The harness
  would use `StreamPeerTCP` to a 127.0.0.1 ephemeral port the daemon picks and injects
  via the launch marker (token-authenticated, still no scan). Rejected **for UNIX**:
  it adds a second transport and a loopback listener for a brand-new capability with no
  4.4/4.5 live users, where UDS-everywhere is uniform and surface-free. **This rejected
  option is exactly the forward path for Windows** (see Consequences), where UDS is
  unavailable.
- **godot-mcp-pro's fixed TCP port-range scan (`6505–6514`).** Rejected: brittle under
  port collisions and multiple projects; UDS keys cleanly on a per-project path.
- **A discovery registry / daemon-of-daemons.** Rejected: a deterministic per-project
  path + pidfile is the simplest thing that supports the per-project model; a registry
  is unwarranted machinery.
- **A bespoke daemon↔harness wire format.** Rejected: reusing the ADR-0002 sentinel is
  what lets the entire classify/parse/emit pipeline be reused unchanged.

## Consequences

- The live stack is **uniform UDS**: one transport, one discovery story, no localhost
  surface, no token handshake required for the harness port (there is no port).
- **Non-UNIX (Windows) platforms.** Both legs are UDS — `AF_UNIX` (Python, the
  CLI↔daemon leg) and `StreamPeerUDS` (GDScript, the daemon↔harness leg) — and both are
  UNIX-only, so the **entire** Phase-2 live stack (not merely the harness leg) is
  **macOS/Linux only**; there is no partial degradation. The boundary is deliberate and
  contained:
  - **Phase-1 headless is unaffected and stays cross-platform** — it spawns one-shot
    `godot --headless` subprocesses and never touches the daemon or a socket, so a
    Windows user keeps the full headless surface.
  - **Fail fast, not cryptically.** On a non-UNIX platform `gda daemon start` (and any
    live command's attach-or-fail) returns a **typed structured error** — candidate
    code `live_unsupported_platform` — whose message names the limitation and that live
    is UNIX-only today, rather than surfacing a raw socket error. `--help` / `--schema`
    for the `daemon` group and live commands state the UNIX-only constraint.
    The platform check precedes the version check (it needs no engine launch).
  - **Future Windows support is out of scope here, left to its own ADR.** A *candidate*
    path — should it be pursued — is the localhost-TCP daemon↔harness variant above (with
    a named-pipe or TCP CLI↔daemon leg); that future ADR + slice evaluates the transport
    on its own facts. It is named here only to show the cutoff is not a dead end; it is
    **not** decided now, would **not** raise the headless floor, and does not block this
    slice.
- **Amends ADR-0003**: the live floor is 4.6; a pointer is added on ADR-0003. The
  headless floor is untouched.
- **Implementation constraint**: socket/pidfile paths must respect the `sun_path`
  length limit (short runtime dir).
- **Candidate error codes** (registered in `src/gda/error_codes.py` + the ADR-0002
  table by the implementing slice, per ADR-0002 — *not* accepted ABI here, and
  classifier-source so none are GDScript-mirrored): `daemon_not_running`,
  `engine_session_not_running` (daemon up, no live session), `engine_disconnected`
  (session lost mid-op), `live_timeout`, `live_unsupported_platform`, and the
  live-version-floor reuse of the ADR-0003 `version` gate. The first four are
  live-runtime failures (candidates for a new `ErrorCategory.LIVE`, ADR-0017);
  `live_unsupported_platform` is instead an **`environment`**-category code — a
  pre-launch platform precondition (no `AF_UNIX`), the same bucket as
  `binary_not_found` / `launch_timeout`, decided before any engine launch.
- **Closes the open transport/discovery item** carried by ADR-0017, PRD #6, and #7.
