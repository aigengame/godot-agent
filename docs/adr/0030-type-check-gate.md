---
status: accepted
---

# Type-check gate: pyright (`basic`), `src/` first, enforced in CI

> **Outcome (Stage 2, 2026-06-27):** the gate now also covers `tests/` (#308) — `[tool.pyright]`
> `include` is `["src", "tests"]` and the whole repo type-checks clean (the 109 test findings were
> resolved with union-narrowing helpers, not-None asserts, `cast`s for intentional test doubles,
> and `ListRootsFnT`-typed in-memory callbacks). The "`tests/` out of scope / Stage 2 / src-only
> end-state" framing below is the point-in-time Stage-1 record.

CI gates lint + format (ruff, [ADR-0029](0029-lint-and-format-gate.md)), tests, and build —
but nothing checks types. There is no type-checker config, no type-checker dev dependency,
and no `py.typed`. Yet `src/` is heavily annotated (0 `type: ignore`) and the structured-output
Pydantic models **are the public ABI** ([ADR-0002](0002-headless-structured-output-contract.md),
[ADR-0015](0015-structured-params-input-abi.md)). So nothing enforces the type discipline the
code already practices, and nothing guards None-safety or ABI-shape drift that ruff's F-rules
cannot catch. This ADR records the type-level sibling of the ruff gate.

## Decision

**Enforce a type-check gate with pyright in `basic` mode, scoped to `src/`, in CI.** Rolled out
in stages (issues #307–#309); this ADR covers the Stage 1 `src/` gate.

- **Tool: pyright (pinned dev dependency, locked in `uv.lock`).** Zero-config, fast, and it
  infers Pydantic/Typer out of the box; CI runs `uv run --frozen pyright`. Pinned because a
  pyright upgrade can add new checks — so the bump is a deliberate `uv.lock` change, reviewed on
  its own, not a surprise PR failure (same stance the ruff pin takes).

- **A parallel `type-check` CI job**, mirroring the ruff `lint` job — reuses the
  `setup-python-env` composite with `save-cache: false` (the `python` job populates that key),
  fails fast, and gives an independent signal.

- **Mode `basic`, scope `src/`.** `[tool.pyright]` sets `include = ["src"]`,
  `pythonVersion = "3.13"`, `typeCheckingMode = "basic"`. `basic` is the high-signal starting
  point; `strict` would add hundreds of `reportUnknown*` findings at once. The 109 `tests/`
  findings (mostly union-narrowing noise) are out of scope here — extending the gate to `tests/`
  is Stage 2 (#308), a strictness ratchet is Stage 3 (#309).

- **The 21 `src/` findings were resolved in three honest ways**, not blanket-ignored:
  - *Real None-safety / narrowing fixes* (the majority): a guard returning a structured
    `engine_disconnected` when a session has no connection; a boundary guard that **drops** a
    malformed daemon control frame (a non-dict value, or a missing/non-string `op`) and isolates
    per-request decode/handle failures in the serve loop, so malformed IPC can never crash the
    daemon ([ADR-0021](0021-gda-daemon-transport-discovery-and-live-version-floor.md)) — this
    also narrows `op` to `str`; an `assert cmd.recipe is not None` documenting the recipe-dispatch
    invariant ([ADR-0023](0023-command-descriptor-single-registration.md)); a guard restructured
    to narrow a `Path | None`; `render_node_tree` widened to `SceneNode | GameNode` (the two share
    `name`/`type`/`children`); and `surface.py` switched to the `getattr` idiom it already uses.

    > **Outcome (2026-08-15, ADR-0040):** `render_node_tree` now types against the structural
    > `NodeOutline` protocol in `gda.render` (the shared `name`/`type`/`children` view), so the
    > union of the two concrete models — which became an upward edge after the group split —
    > is gone.
  - *Honest annotation widening*: the `classify_*` functions that only interpolate `binary` into
    a message take `Path | None`, since live ops legitimately pass `None`.
  - *Two reasoned suppressions*: the `reportRedeclaration` analogue of ruff's `F811` cli.py
    ignore (the Typer same-named-subcommand idiom, ADR-0023), suppressed file-wide in `cli.py`;
    and two `# pyright: ignore[reportArgumentType]` on the shared `RunnerFactory`/`Classifier`
    dispatch seam, where `binary` is `None` only for live ops whose injected runner/classifier
    ignore it ([ADR-0017](0017-gda-daemon-live-execution-mechanism.md)) — a precise type there
    would cascade across ~15 sites.

    > **Outcome (2026-08-15, [ADR-0040](0040-per-command-group-modules.md)):** the file-wide
    > `cli.py` `reportRedeclaration` suppression was removed with the per-command-group split
    > — command function names are unique per group module, so `cli.py` no longer redefines
    > names. The two `headless.py` seam ignores stand.

## Considered options

- **pyright (chosen).** Zero-config, fast, strong Pydantic/Typer inference, pins via `uv.lock`,
  runs through `uv run` with a self-bundled Node — no separate CI Node setup.
- **mypy (rejected).** The de-facto standard, but needs the `pydantic.mypy` plugin for the
  model-heavy code and is slower; no advantage here over pyright.
- **Astral `ty` (deferred).** Aligns with the repo's uv + ruff toolchain (ADR-0029) and already
  runs here (65 diagnostics), but is pre-release — gating CI on it now is premature. Tracked as a
  future migration in Stage 3 (#309).
- **`strict` mode now (rejected).** Hundreds of findings in one step; ratchet from `basic`
  instead (#309).
- **Gate `tests/` in the same step (deferred).** The 109 test findings are mostly union-narrowing
  noise; cleaning them with a shared helper is Stage 2 (#308), and `src/`-only is a legitimate
  end-state.

## Consequences

- The `cli.py` file-wide `reportRedeclaration=false` (like the ruff `F811` ignore) also masks a
  *genuine* accidental redefinition in that one module. Accepted: `cli.py` is the
  command-registration module, dominated by the intentional idiom; a real clash would surface as
  a broken command, not silently.
  > **Outcome (2026-08-15, [ADR-0040](0040-per-command-group-modules.md)):** this risk ended
  > when the suppression was removed — `reportRedeclaration` now covers `src/` without
  > exception.
- The two `headless.py` seam ignores are the one place a finding is suppressed rather than fixed
  in `src/`; both carry the invariant in a comment. Tightening the `RunnerFactory`/`Classifier`
  seam to express the per-kind binary invariant is possible but deliberately not taken now.
- README's Development/Contributing sections document `uv run pyright` + the gate. **No ADR link
  in the README** — it is human-facing onboarding, not an ADR index (the Contributing section's
  general `docs/adr/` pointer suffices).
- No new CONTEXT.md term: a type gate is build tooling, not a domain concept.
- Verified in #307: `pyright` reports 0 on `src/`, the `type-check` job is green, and
  `pytest -m "not e2e"` is unaffected. The gate was negative-tested at PR time with a deliberate
  type error (pyright then exits non-zero); that proof is **not** checked in, because a
  permanently-broken file would have to be excluded from the very gate it tests — the gate runs
  on every PR, so it is itself the durable regression mechanism (the same model as the ruff gate,
  ADR-0029).
