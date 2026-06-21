---
status: accepted
---

# Target Godot version: 4.x, minimum 4.4, tested against 4.6

> **Amended by [ADR-0021](0021-gda-daemon-transport-discovery-and-live-version-floor.md)
> (2026-06-21, #7) for the live layer:** Phase-2 [live operations](../../CONTEXT.md)
> require **Godot ≥ 4.6**, because the daemon↔harness transport is a Unix domain socket
> and `StreamPeerUDS` landed in 4.6-stable. The minimum stated below **stands unchanged
> for the Phase-1 headless layer (4.4)** — headless uses neither the daemon nor UDS. UDS
> is also UNIX-only, so live is macOS/Linux only; headless stays cross-platform.

GDScript APIs, `--headless` behaviour, and `Engine.get_version_info()` fields all
vary across Godot versions, and the 3.x and 4.x lines are effectively two different
engines. `gda` must declare which versions it supports so that e2e tests can assert
against a concrete version and GDScript operations can be written to one API set.

We target **Godot 4.x**, with a **minimum supported version of 4.4** and **4.6 as the
development/test baseline**:

- 4.4 is the floor where the modern features we rely on exist (UID management, stable
  headless behaviour) and is the common baseline of both reference implementations
  (`godot-mcp`, `godot-mcp-pro`).
- 4.6 is the locally installed engine, so e2e tests ([headless operations](../../CONTEXT.md))
  run against it.

`gda` resolves the actual engine version via `gda info` (`Engine.get_version_info()`).
When the detected version is below the minimum, `gda` returns a **structured error**
(the environment-error shape from ADR-0002 / issue #3) rather than failing implicitly,
making "version too old" a programmatically detectable failure.

## Considered options

- **min 4.4 / tested 4.6** (chosen) — supports a sensible modern range while pinning a
  concrete baseline for tests.
- **Pin a single version (4.6 only)** — simplest and most deterministic, but brittle:
  any other engine version an agent has installed could silently misbehave.
- **Broad 4.0+** — widest coverage, but 4.0–4.3 lack features and differ in headless
  behaviour, raising verification cost beyond what the MVP warrants.

## Consequences

- e2e tests assume 4.6 locally; CI/other machines must provide a 4.4+ engine.
- 3.x is explicitly unsupported.
- The minimum-version check depends on the `gda info` operation (issue #2) existing.
