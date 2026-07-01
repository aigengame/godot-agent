---
status: accepted
---

# gda surface inclusion: agent value + structured-operation fit, not engine-CLI parity

ADR-0005 fixed *how* `gda` commands are named and grouped; it did not fix *which* engine
capabilities earn a command. As the surface grows, a recurring question keeps returning —
"should `gda` wrap Godot feature/flag X?" (most recently: run a project / run a specific scene;
before that: `.cs` support, asset import). Answering it ad hoc invites two opposite failures:
importing engine flags with no agent value (surface bloat), or refusing capabilities that clearly
advance the agent loop (gaps). This ADR records the inclusion criterion.

## Decision

`gda` is **not a CLI wrapper over the engine launcher.** It is an agent-facing layer of
**structured operations** — most of which the engine CLI does not expose at all (`node add/set`,
`script set`, signal wiring, …), expressed through gda's own GDScript payload. So the surface is
**not** driven by parity with `godot --help`.

**Inclusion criterion — wrap an engine capability as a `gda` command iff both hold:**

1. **Agent value** — it advances the agent's write → run → observe → fix loop, or a
   CI/automation need an agent drives. (Not: human-interactive editor/dev tooling.)
2. **Structured-operation fit** — it can be expressed as a typed operation behind gda's contract:
   one `--json` result, a `--schema` self-description (ADR-0004), and a stable `GdaError` envelope
   (ADR-0002). Streaming, an interactive REPL/stepping loop, and editor-GUI state do not fit.

A capability failing either test stays out, regardless of how prominent the engine flag is.

> **Outcome (2026-06-30, #343):** `--script` one-shot is now **committed** — a concrete agent need
> appeared (headless logic-seam tests, dogfooding #329/#341). Its execution shape and result contract
> are recorded in ADR-0031 (`gda script run`). The other case-by-case candidates (`--check-only`,
> `--import`) remain undecided under this same criterion.

**Worked classification (Godot 4.6 `--help`) — illustrative, not a roadmap.** The lists below show
the criterion *applied*; they are **non-binding examples**, not surface decisions made by this ADR.
Only "run a project / a specific scene" is **committed** here (via #278); `export` is already shipped.
Every other entry remains its own future decision under this same criterion.

- *In, by this criterion:* running a project / a specific scene (committed — ADR-0017 amendment, #278),
  export (already `gda export run`), and — case by case, **only if a concrete agent need appears** —
  `--script` one-shot, `--check-only`, `--import`.
- *Out, by this criterion:* editor / project-manager GUI, debugger / LSP / DAP servers, rendering /
  display / audio drivers, GPU / profiling internals, `--doctool` / `--gdscript-docs` /
  `--dump-extension-api` codegen, `--build-solutions`, `--convert-3to4`, debug visualizers — no agent
  value and/or no structured-operation fit.

**Corollary — interactive debugging is out; observability is in.** Godot's remote-debug protocol
(`--remote-debug`) offers rich data, but its variable inspection / breakpoints / step / eval require
a *paused* game, which fails criterion 2 (and contradicts gda's async one-shot-RPC and
frame-coherence, ADR-0011 / 0017 / 0020). Read-only structured signals from it (error callstacks,
profiler frames) may qualify; the interactive surface does not. Any tap of that protocol is its own
ADR.

## Considered options

- **Mirror the engine CLI for completeness (rejected).** Produces bloat (dev-tooling flags) and is
  incoherent — gda already exceeds the CLI with structured ops the CLI lacks.
- **Add capabilities purely on request, with no stated criterion (rejected).** The status quo; it
  re-opens the same debate per feature and drifts.
- **A stated inclusion criterion (chosen).** Gives every future "should gda support X?" a durable,
  one-paragraph answer and keeps the surface coherent with ADR-0001 / 0004 / 0005.

## Consequences

- "Run a project / a specific scene" is in scope; the first slice is #278 (ADR-0017 amendment).
- Engine dev-tooling flags stay out unless a concrete agent need re-qualifies one, each as a typed op.
- Interactive debugging stays out; structured observability (errors + callstacks, perf) is the model.
  Tapping Godot's remote-debug protocol for the read-only parts is deferred to its own ADR.
- This criterion governs `gda`'s scope only; it does not change command naming/grouping (ADR-0005 /
  ADR-0019). The concrete entry point for the accepted run surface is `gda daemon start --scene`
  (#278); any `scene play` / `game run` wrapper is a separate follow-up.
- The concrete command placement and any `docs/command-catalog.md` entry for the run surface land
  with the implementation slice (#278), **not** this principle ADR — the catalog is a non-binding
  feature map and committed status is tracked in the issue tracker (the milestone), so the accepted
  surface is intentionally not pre-catalogued here.
