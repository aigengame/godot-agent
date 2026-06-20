---
status: accepted
---

# Phase-1 trust boundary: gda operates on a trusted project

Issue #30 established that *reading* a scene must not execute project code, and
the read operations honour it at the operation level: `scene get`, `node list`,
and `scene list` walk `SceneState` (`packed.get_state()`) without instantiating
anything (`src/gda/ops/operations.gd`). But two findings showed that "no project
code runs" was never true of a whole `gda` invocation:

- **Autoloads run on every `--project` operation (#61).** The runner passes the
  resolved project as `--path` uniformly for every command (`src/gda/runner.py`),
  and `operations.gd` is a `SceneTree` main loop. The engine therefore constructs
  the project's autoload singletons during startup — running their `_init`/`_ready`
  — *before* our operation script gets control, on read-only commands included.
- **Instantiating operations run scene scripts' `_init` (#62).** Mutating a scene
  requires a real node tree: `_load_for_mutation()` calls `PackedScene.instantiate()`,
  which constructs every node and runs the `_init` of any attached non-`@tool`
  script. This is unavoidable on the mutate path given the one-shot headless design
  (ADR-0001). `node get` is a *read* command that also instantiates (to report
  runtime property defaults `SceneState` does not store), so it sits on the same
  surface despite not mutating.

## Decision

**Phase 1 assumes the target project is trusted.** `gda` operates on the project
the agent is building (resolved via `--project`/`$GDA_PROJECT`/cwd, ADR-0006); it
does not defend against a malicious or untrusted project. Executing that project's
own autoload and scene-script constructors is therefore expected behaviour, not a
vulnerability, and we **accept and document** it rather than harden in Phase 1.

> Extended by ADR-0018: Phase 2 adds a second axis to this boundary — `gda` is also
> assumed to be the project's *sole driver*; a concurrent external editor's writes are
> out of scope, for the same accept-and-document reasons.

The documented [project-code execution surface](../../CONTEXT.md) is classified by
**mechanism**, on two orthogonal axes — not by a read/mutate split, because
`node get` is a read that instantiates:

- **Process startup (every `--project` op):** the engine constructs the project's
  autoloads and runs their `_init`/`_ready`, regardless of which command runs.
- **Operation level:**
  - *State-read operations* walk `SceneState` and execute **no** project code at the
    operation level — `scene get`, `node list`, `scene list`.
  - *Instantiating operations* call `PackedScene.instantiate()` and execute the
    `_init` of scripts attached to the scene's nodes — `node add`, `node set`,
    future mutate operations, **and** `node get`.

A forged result sentinel emitted by an executed script does not produce a silently
believed result: a second `<<<GDA:RESULT>>>` payload on stdout makes the command
fail loudly with `contract_violation` (exit 5, ADR-0002).

## Consequences

- **#30 is rescoped, honestly.** Its "reading executes no project code" guarantee
  holds at the operation level *for state-read operations only*. It does not cover
  process-startup autoloads (#61), and it does not cover instantiating reads like
  `node get` (#62). The claim is scoped to *that mechanism*, not to all of `gda`.
- **Autoload suppression is a possible future robustness enhancement, not a security
  fix.** The file-level Phase-1 operations never need the project's autoloads, so a
  broken or heavyweight autoload `_init` only adds noise or can fail an unrelated
  read. Suppressing autoloads in one-shot headless runs (if feasible — feasibility
  is itself unestablished) would improve robustness; it carries no security
  obligation under this trust boundary and is not committed here. It would be its
  own slice with its own justification.
- **Untrusted-project safety is explicitly out of scope for Phase 1.** Hardening
  directions (OS-level sandboxing, text-level `.tscn` editing that bypasses engine
  semantics) are heavy and were rejected for Phase 1; if a use case for operating on
  untrusted projects emerges, it warrants its own ADR rather than an incremental
  patch.
- The factual user-facing warning (README) and the characterization tests that pin
  this surface are tracked by #63.
