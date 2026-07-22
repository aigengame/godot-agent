---
status: accepted
---

# Invocation result contract: one JSON result, refusal-carrying error envelope, layered exit codes

> **Standard Schema 2.x outcome (2026-07-22):** this record remains accepted for the 1.x surface.
> [bADR-0015](0015-invocation-outcomes-and-diagnostic-locations.md) supersedes its closed 1.x envelope
> for new refusal stages and locations, and
> [bADR-0021](0021-schema-2.0-cli-taxonomy-and-structured-surface.md) owns 2.x artifact publication.
> The five-way outcome algebra, exit/channel meanings, one structured payload, and sanitized
> internal failure remain retained constraints.

PRD #501 US19 requires structured JSON output and typed machine-readable refusals
distinct from pass/fail verdicts; bADR-0004 fixes the refusal semantics and hands their
CLI surface — envelope shape and exit codes — to this gate (#518). This bADR fixes what
one `gda-balancing` invocation returns: the output channels, the success and failure
payloads, and the exit-code layering. It carries the funnel's refusal codes; it mints exactly one
new code family (CLI usage) plus the single fixed `internal_error` code, and no
refusal codes.

## Decision

- **One structured JSON payload per invocation** *(adopted-from-gda principle:
  ADR-0002; JSON-first per bADR-0005)*. A successful command emits its typed result
  object — canonically emitted per bADR-0005 — as the only content on stdout. Human
  diagnostics and progress go to stderr; stderr is never parsed for outcome
  *(adopted-from-gda: ADR-0002's channel discipline)*. The invariant is
  channel-invariant: with `--out` (bADR-0009) the artifact body moves to the sink
  while stdout still carries the typed result as the receipt — `--out` never forks
  the result contract.

- **JSON by default; no human renderer in v1.** *(Recorded deviation from gda's
  human-default + `--json` flag.)* This toolkit is agent-first with no human-terminal
  install base: every Phase-1 consumer is an agent, CI, or a test, and bADR-0005
  already makes JSON the authoritative serialization for toolkit reports. Defaulting
  to JSON removes the forgot-`--json` failure class entirely. Precedent exists on both
  sides (AWS CLI v2 is JSON-by-default; gh/Terraform render human-first) — this is a
  recorded adjudication (maintainer-approved, 2026-07-18), not drift. A human render
  may arrive later behind an explicit additive flag (e.g. `--format human`) without
  contract change.

- **No sentinel wrapping.** *(Recorded deviation from gda ADR-0002.)* gda's sentinels
  exist because it parses an engine subprocess's stdout, where engine noise
  interleaves with the payload. This toolkit spawns no subprocess and owns its stdout
  end to end, so that risk class is structurally absent; the payload is a plain JSON
  document. (Research: cargo documents plain JSON-per-line on stdout and its
  `starts with {` sniffing caveat exists precisely for *foreign* output interleaving —
  the precondition this toolkit does not have.)

- **The error envelope.** Any failed invocation emits exactly one envelope object,
  recognizable by its single top-level `error` key *(adopted-from-gda: ADR-0002's
  envelope pattern; field set is balancing-local)*:

  ```json
  {"error": {"category": "...", "code": "...", "message": "...",
             "refusals": [{"code": "...", "path": "...", "detail": "..."}],
             "truncated": false}}
  ```

  - `category` ∈ `refusal` | `usage` | `internal` — the discriminator agents branch
    on. (A verdict is not an error and never appears here; see the exit table.)
  - `refusal` envelopes carry the refusal report verbatim: each entry is bADR-0004's
    typed refusal — stable `code`, `path` (bADR-0004's instance path, an RFC 6901
    JSON Pointer), human `detail` — with bADR-0004's report-all list semantics
    (deduplicated, path-then-code order, ≤ 1000 entries, explicit `truncated`
    marker). Envelope-level `code` is absent for refusals: the codes live in the
    entries, and **this contract mints no refusal codes** — the carried namespace is
    the funnel's families (preflight + structural + the semantic rule catalog,
    bADR-0004) plus the one downstream class, the non-finite Evaluation refusal
    family (bADR-0003).
  - `usage` and `internal` envelopes carry a single envelope-level `code` and no
    `refusals` list. Internal errors use the single fixed code `internal_error`,
    registered in the same registry as the CLI-usage family (bADR-0011).
  - **Field law (normative).** `category` and `message` are required in every
    envelope. For `refusal`: `refusals` (non-empty) and `truncated` are required,
    envelope-level `code` is forbidden. For `usage`/`internal`: `code` is
    required, `refusals`/`truncated` are forbidden. Two optional members exist:
    `diagnostics` (string, `internal` only, populated only under `--debug` — see
    below) and `reproduction` (below). No other member is permitted — the envelope
    schema is closed, and it is exactly the uniform `error` schema `--schema`
    publishes (bADR-0009).

- **The CLI-usage code family — the one family this contract mints** *(new ground)*.
  Its boundary is the funnel's ingress: **everything that fails before the document's
  bytes reach the funnel is a usage error** (unknown command or flag,
  mutually-exclusive arguments, an unreadable input path); **everything after is a
  typed refusal** — the funnel's phases (unparseable JSON, caps, version dispatch,
  structure, semantics; bADR-0004) and, past an accepting funnel, the one downstream
  class, the non-finite Evaluation refusal (bADR-0003). The **v1 normative code
  set**: `missing_command`, `unknown_command`, `unknown_argument`,
  `argument_conflict`, `invalid_argument`, `unreadable_input`,
  `unwritable_output`. The family's codes
  live in the single registry the conformance harness walks (bADR-0011); additions
  are additive registry entries, never renames, and the seam keeps the two
  namespaces from ever overlapping.

- **Exit-code layering** *(new ground — no dominant industry precedent; this layout is
  the toolkit's own assembly of individually verified precedents, recorded per the
  #518 research)*:

  | Exit | Meaning | Payload | Channel | Status |
  |---|---|---|---|---|
  | `0` | success (incl. validate-passed; later verdict-pass) | result object | stdout | v1 |
  | `1` | **verdict-fail** — a *valid* design judged failing its balance targets | verdict report (shape owned by Phase-2 design) | stdout | reserved |
  | `2` | **refusal** — typed refusals rejected the document (funnel phases, or the downstream Evaluation refusal) | `refusal` envelope | stdout | v1 |
  | `3` | **usage error** — the invocation itself is malformed | `usage` envelope | stderr | v1 |
  | `4` | **internal error** — the toolkit itself failed | `internal` envelope | stderr | v1 |

  - Channel follows meaning: exits 0–2 are the command *doing its job* (a refusal
    report **is** `design validate`'s product on an invalid document), so their
    payload is stdout content; exits 3–4 mean no job was done, so stdout stays empty
    and the machine-readable envelope goes to stderr (precedent: rustc's JSON
    diagnostics on stderr; clig.dev's messaging-to-stderr; #502's tracer acceptance).
  - Verdict-fail sits adjacent to success (grep/diff/pytest's 40-year form: exit 1 is
    a negative *answer*, not a malfunction); usage and internal stay separate rather
    than collapsed linter-style, because the conformance harness must distinguish
    "you called it wrong" from "the tool broke" *(pytest's four-way layering is the
    closest live precedent; ESLint/Ruff's three-bucket collapse is the recorded
    counter-practice)*.
  - An unsupported or malformed `schema_version` is a **preflight refusal (exit 2)**,
    not a usage error — version dispatch is the funnel's (bADR-0001/0004).
  - All codes stay far below the shell-reserved band (126/127/128+N).
  - *(Recorded deviation from gda's exit codes: gda's 3 version / 4 operation /
    5 parse / 6 live / 124 / 127 classify engine-wrapper failure sources — binary
    resolution, launch, engine crash, live channel — none of which exist here. The
    refusal/verdict split gda has no analogue for is bADR-0004's mandate.)*
  - `1` is reserved **now** so Phase-2 (#509) inherits it as fixed contract; nothing
    may repurpose it meanwhile, and the internal-error exit does not shift when the
    verdict channel is delivered.

- **Failure stderr is exactly one sanitized JSON document.** For exits 3 and 4,
  stdout is empty and stderr carries the envelope and nothing else — no banner, no
  trailing traceback — so the failure channel is machine-parseable whole, never by
  line-sniffing. An unexpected exception's detail (traceback, paths) appears only
  inside the envelope's `diagnostics` field and only under an explicit `--debug`
  flag; the default `internal` envelope carries the stable code and a sanitized
  message. A bare traceback is never any invocation's output.

- **Failures after stochastic execution starts carry the reproduction key.** Once a
  stochastic command (bADR-0010) has drawn its effective seed, any failure envelope
  it emits — e.g. a Monte-Carlo run hitting the non-finite Evaluation refusal —
  includes `reproduction: {seed, toolkit_version}`, so the replay key is never lost
  to the failure path. Deterministic commands never carry the member. (No v1
  command is stochastic; #510 inherits this with bADR-0010.)

## Considered options

- **Layered small integers, envelope by category** (chosen).
- **Human-default output with `--json`** (rejected) — see the recorded deviation
  above; it optimizes for a consumer this product does not have.
- **Sentinel-delimited payload** (rejected) — solves an interleaving risk this
  toolkit structurally lacks; pure ceremony here.
- **sysexits integers (`EX_USAGE=64`, `EX_DATAERR=65`)** (rejected) — the only
  written usage-vs-data standard, but unadopted by the canonical small-integer tools
  (grep/diff/git, verified), and alien to the family's small-integer style; adopting
  the *distinction* does not require adopting the integers.
- **Linter-style collapse (usage + internal in one code)** (rejected) — erases a
  distinction the conformance harness and agents both branch on.
- **Everything on stdout** (rejected) — a malformed invocation would still "produce a
  result", muddying stdout-as-product; contradicts the channel-meaning precedent and
  #502's recorded tracer expectation.
- **Refusal report on stderr** (rejected) — the refusal report is the primary product
  of a validation run and the batch-fix input for agents (bADR-0004's report-all
  rationale); hiding the product on the diagnostics channel serves no one.
- **Bare typed result object on success, envelope only on failure** (chosen) — one
  top-level `error` key is the in-band discriminator; exit code is the out-of-band
  one.
- **Uniform wrapper around success results too** (rejected) — a second envelope with
  no discriminating job; the success schema is already per-command via `--schema`
  (bADR-0009).

## Consequences

- #502's version tracer implements exits 0/3 and the `usage` envelope; #504
  implements exit 2 and the `refusal` envelope end to end.
- The conformance harness (bADR-0011) asserts, per registered command, every
  applicable row of the exit table and both envelope channels.
- The `refusal` envelope is the single CLI carrier of bADR-0004 refusals; any future
  command that can receive a document inherits it unchanged.
- Exit `1` and the verdict-report shape are the fixed inheritance of the Phase-2
  design gate (#509) — reserved, never redesigned there.

## References

- gda ADR-0002 (structured output contract) — reference input; deviations recorded
  above. bADR-0003/0004 own every refusal code this envelope carries.
- Research provenance (non-normative): issue #518 comment (2026-07-18) — exit-code
  precedents (sysexits, pytest, grep/diff, ESLint/Ruff, Bash reserved band), output
  conventions (cargo, rustc, AWS/gh/Terraform, RFC 9457 congruence with the refusal
  triple).
