---
status: accepted
---

# Headless structured output: sentinel-delimited JSON on stdout

> **Outcome (2026-06-23, #260):** the sentinel result format now has a single home
> for both directions — `gda.parser.build_result` (write) is the inverse of
> `gda.parser.parse_result` (read) — and a daemon- or live-client-synthesized reply
> is built once through `gda.daemon.protocol.result_reply` / `error_reply` (the
> latter over the shared `gda.parser.error_envelope`), replacing four hand-rolled
> copies of the `<<<GDA:RESULT>>>…<<<GDA:END>>>` wrapping. No contract change — the
> emitted bytes, exit codes, and envelope shape are identical.

Structured output is `gda`'s core differentiator (ADR-0000), but a headless Godot
process mixes its version banner, warnings, errors, and `print()` output into
stdout/stderr. `godot-mcp` does not solve this — it returns the raw stdout blob as
text, leaving the agent to parse noise.

For [headless operations](../../CONTEXT.md) we define a result contract:

- The GDScript emits **exactly one** result payload to **stdout**, wrapped in unique
  sentinels: `<<<GDA:RESULT>>>{...json...}<<<GDA:END>>>`.
- On success, the sentinel payload is the command's result object and the process
  exits `0`.
- On operation failure, the sentinel payload is a minimal error envelope with an
  operation-reported error code and message, and the process exits non-zero. `gda`
  validates the reported code, assigns the `operation` category, and attaches
  stderr diagnostics before emitting the public `GdaError`.
- The GDScript routes **all** of its own diagnostics (logs, warnings, progress) to
  **stderr**. stderr is diagnostic only; it is never parsed for stable error codes.
- `gda` extracts the bytes between the sentinels and parses that as the result;
  everything else on stdout is ignored, and stderr is surfaced for diagnostics.
  The payload echoes user-controlled content (a path, and later node names /
  script source) that may itself contain the end sentinel text, so extraction
  takes the **last** end sentinel after the begin sentinel as the terminator.
  This rests on two invariants below: the operation emits exactly one result and
  writes nothing else to stdout, so any sentinel-shaped bytes are payload content
  *before* the real terminator and cannot truncate the result (issue #34).
- A **result file** (a path passed in by `gda`, written by the GDScript) is reserved
  as an escape hatch for large or binary payloads that should not stream through
  stdout.

## Failure contract

The process exit code selects the success/failure channel; the sentinel payload
provides the structured detail for that channel:

- `exit_code == 0` plus a success payload means success.
- `exit_code == 0` plus an error envelope is a structured-output contract
  violation.
- `exit_code != 0` plus a valid, registered operation error envelope means an
  `operation` failure with the reported code and message.
- `exit_code != 0` without a valid operation error envelope falls back to
  `operation_failed`.

An operation failure payload has this wire shape:

```json
{"error":{"code":"path_not_found","message":"scene file does not exist: res://missing.tscn"}}
```

The GDScript payload owns only `code` and `message`. `gda` owns the public
`GdaError` wrapper: it validates that the code is registered, assigns the
`operation` category, preserves the message, and copies stderr into diagnostics.

> **Scope note (2026-08-17, #667) — the shape above is the GDScript-emitted
> *headless* payload, and stays exactly that.** The Phase-2 **live** channel reuses
> this envelope but is emitted by Python (the daemon and the daemon IPC client), and
> it carries one OPTIONAL extra key: `probe`, the host-probe context behind a windowed
> refusal (ADR-0004 amendment). The two channels validate against **different models**
> — `OperationErrorEnvelope` (headless) stays `extra="forbid"` and probe-less, because
> a GDScript operation has no host probe to report; `LiveErrorEnvelope` accepts the
> optional key. The key is omitted when absent, so every payload either language
> emitted before is byte-identical. This widens no cross-language contract: GDScript
> neither emits nor reads `probe`.

### stderr as advisory diagnostics

stderr is still **never** parsed for the success/failure *outcome* or for stable
error codes — those come only from the exit code and the stdout sentinel, as
above. A command **may**, however, surface engine error text from stderr as
**advisory, best-effort diagnostics** on its *success* result, when a useful
detail is available nowhere else. `script validate` (#118) is the established
case: when it reports `valid=false`, the per-error `line` and `message` exist
only in the engine's stderr (no bound API exposes them), so `gda` parses them
into the result's `diagnostics`. This stays within the contract: the diagnostics
are advisory (they may hold only the first error, and `column` is unavailable on
the standard build), and they never determine the outcome or a stable code.

> **Scope note (2026-08-19, #664) — a verdict command may put the same recognized
> sentences in a result FIELD, and may report its own bound as a verdict.**
> `scene preflight` boots a scene and reports how far it got, so two of its answers
> come from outside the stdout sentinel. Neither loosens the rules above; both are
> stated here because a reader will otherwise see them as exceptions.
>
> - **A verdict field derived from stderr.** The op's sentinel reports readiness;
>   whether the scene started *cleanly* also depends on the engine's error stream,
>   which the command reads with the SAME recognized-sentence parser #651 owns (no
>   free-text matching, no second parser) and publishes as `diagnostics`. The
>   success/failure OUTCOME — which envelope is emitted, and every stable code —
>   still comes only from the exit code plus the sentinel, exactly as above. What is
>   new is that a *field of a success result* (`started`) is derived from the
>   advisory stream rather than merely carrying it. The rule that matters is
>   unchanged: an unrecognized line changes nothing, and the op's own verdict is
>   never overridden — `status` is reported as the engine gave it.
> - **The launch bound as a verdict, not `launch_timeout`.** `status: timeout`
>   means the complete preflight — startup plus the `--frames` observation
>   window — did not finish within gda's wall-clock bound. A `_ready` that never
>   returns is one possible cause (it blocks the engine before any frame runs, so
>   no sentinel can ever arrive); a healthy, already-ready scene whose frame
>   window outruns the ceiling is another — the params contract states the two
>   bounds are not cross-checked. Either way the run is reported as a SUCCESS
>   carrying `status: timeout` (with the captured diagnostics), not as the
>   `launch_timeout` envelope every other launch-backed channel reports. The
>   difference is what the timeout MEANS: elsewhere it means gda could not get you
>   an answer, while here the question was whether this scene completes its
>   preflight within the bound — so the bound being reached IS the answer. *(#787
>   note, 2026-09-01: the SHAPE difference stands, but the numeric EVIDENCE is now
>   at parity — the timeout verdict carries `elapsed_seconds` and `timeout_seconds`
>   read off the same launch measurement the `launch_timeout` envelope publishes.)*
>   Scoped
>   to this command: an
>   unlaunchable binary, an unusable user-data placement, a signal death, and the
>   op's own structured refusals stay the shared envelope.

> **Scope note (2026-08-18, #663) — one operation, several scripts: the advisory
> stream needs a delimiter.** `script validate` now validates a BATCH of scripts in
> one op (#663), so the stderr it parses carries several scripts' errors in one
> stream and "which script is this about?" has no answer in the engine's output that
> gda can rely on. The op therefore writes its own `gda: validating: <path>` line to
> stderr before each compile, and the classifier splits the stream on those markers
> to attach each script's `line`/`message` pairs to its own entry. This stays inside
> the rule above rather than widening it: the markers are gda's own diagnostics on
> the advisory channel, they carry no verdict (`valid` still comes only from the
> stdout sentinel), and a stream that ever failed to line up leaves the affected
> entry with empty `diagnostics` rather than another script's. It does add a
> cross-language contract — the marker is written in GDScript and read in Python —
> which a test pins on both sides.

> **Scope note (2026-08-15, #651) — the two rules above presuppose the sentinel
> channel, which ADR-0031's `script run` does not have.** Both the "stderr is never
> parsed for the outcome" rule and the "copies stderr into diagnostics" wrapper
> behaviour are stated for the sentinel pipeline, where an outcome is always
> available from the exit code plus the stdout sentinel, and where the engine's
> stderr is the only diagnostic on offer. `script run` (ADR-0031) is a **different
> execution shape**: the entry script is the user's own, so it emits no sentinel,
> and the engine exits `0` even when it never ran the script. Two consequences,
> both scoped to that channel:
>
> - **Outcome.** The engine's error stream is the *only* evidence that the script
>   never ran, so that channel **does** derive its verdict from parsed stderr —
>   keyed on recognized engine sentences, never on free-text matching.
> - **Diagnostics.** `GdaError.diagnostics` is a free-form string, so a channel
>   with better evidence to offer may fill it differently: `script run --strict`
>   carries the user script's own stdout *and* stderr there under fixed labels,
>   because for that failure the script's output *is* the diagnostic.
>
> Neither relaxes the sentinel rules; both record that those rules presuppose a
> sentinel. See the ADR-0031 amendment.
>
> One consequence for the registry below: a row's `source` names the code's
> **authoritative origin channel**, not an exclusive list of what may emit it. When
> the classifier recognizes the same semantic failure from the engine's output
> rather than from a sentinel, it may assign an `operation`-source code — as
> `invalid_path` already does for a CLI-side path rejection. The GDScript mirror is
> derived from operation-source *membership*, which such reuse does not change.

> **Scope note, extended 2026-08-16 (#651 review recheck) — naming the sentences
> this qualifies.** Two accepted sentences read as an exclusive rule and are the
> ones the paragraph above narrows: the registry section's "GDScript mirrors only
> the rows whose source is `operation`, because only those codes can be reported by
> headless operations", and the `Source` column's implied "the source that may
> report it".
>
> Both stay true of what they actually govern — **mirror membership and the
> sentinel channel**: `operations.gd` declares exactly the `operation`-source rows,
> and only those may come back through the ADR-0002 sentinel as an operation's own
> report. Neither constrains the **Python classifier**, which may assign any
> registered code whose semantics match the failure it recognized, including an
> `operation`-source one — a practice `invalid_path` established long before #651.
>
> So: `source` is an **origin-and-membership** field, never an emitter whitelist.
> Nothing derives behavior from the exclusive reading — `classify_run` keys on
> operation-source *membership* to validate a sentinel-reported code, and the
> mirror test keys on the same membership — so this is a correction to the recorded
> meaning, not a change to the contract. `src/gda/error_codes.py`'s module
> docstring is the single home of this definition.

> **Scope note (2026-08-18, #670) — a failure stage that precedes the sentinel: the
> `usage` category, and the envelope's optional `hint`.** Everything above describes
> failures of an operation gda has already identified. Dogfooding kept producing an
> earlier one: gda could not resolve WHAT was asked for — `gda scene inspect`,
> `gda --schema`, `gda script run --script …` — and that failure left the contract
> entirely, as prose on stderr with nothing to branch on (GDA-DF-024/025/032/033/041).
> It now reports through this same envelope, with three consequences recorded here:
>
> - **A sixth category, `usage`**, rather than folding into `operation`: no engine was
>   launched and no operation was named, so `operation`'s meaning ("a launched engine
>   failed to deliver a result") would have been false. It is the one category whose
>   codes cannot be reported by any operation — both are classifier-source and neither
>   is GDScript-mirrored.
> - **Exit `2`, which gda did not choose.** It is the exit every CLI parser already
>   uses for a usage error, and it is what these invocations already exited with, so
>   registering it changes no observable exit code — it only makes the envelope's
>   `exit_code` and the process's agree. `exit_codes.py` gains `EXIT_USAGE` for it.
> - **An optional `hint` on `GdaError`**, the supported invocation to run instead. It
>   joins `probe` on the optional-context axis under the same rule — OMITTED, never
>   `null`, so every envelope emitted before is byte-identical — and it is set only
>   where gda RECOGNIZES the mistake, from a curated table (`src/gda/hints.py`), never
>   from a string-similarity guess that can name a different operation than the one
>   meant. This widens no cross-language contract: neither GDScript surface emits or
>   reads `hint`, and `OperationErrorEnvelope` stays `extra="forbid"`.

> **Outcome (2026-09-02, #685 / #798 / #803) — the HUMAN failure channel, adjudicated.**
> Everything above specifies the envelope; until #685 that was the whole of what gda
> emitted, because a caller who passed no `--json` got the serialized envelope anyway.
> #685 gave the same outcome a second rendering, and the #798 round-1 review flagged
> that this made the human channel a public output surface with no ADR behind it. This
> note is the record. It also gives `CONTEXT.md`'s *Error envelope* entry — "Two
> renderings of ONE outcome, at one exit code, from one renderer" — its ADR backing,
> by reference rather than by restatement.
>
> - **Every gda-classified failure renders for a human on `stdout`, through the one
>   renderer** (`gda.render.render_failure`, reached only via `gda.headless.emit_failure`),
>   the `usage` refusals (`unknown_command` / `unknown_option`) included. Routing those
>   there is what made the one-renderer invariant TRUE rather than approximate, and what
>   made the `hint:` line reachable at all — it is set nowhere else, so before #798 a
>   human could never read it.
> - **The recorded exception is click's own parse errors** (a missing argument, an
>   invalid value), which stay click-formatted on `stderr`: gda never classified them,
>   so it has no envelope to render. The same holds where gda recognizes a mistake but
>   has no correction to add and no `--json` was asked for — it declines to answer and
>   the parser's message stands. That is gda staying silent, not a second gda layout.
> - **`--json` is untouched.** The envelope goes to `stdout` as it always did, byte for
>   byte; the flag chooses the rendering, never the stream.
> - **Reversal was considered and declined**, twice over. Sending the `usage` refusals
>   back to `stderr` resurrects the defect #798 closed — two layouts for one category,
>   and `hint` as a dead branch. Moving ALL human rendering to `stderr` would buy
>   convention compliance at the cost of a cross-channel asymmetry with `--json`, plus a
>   documentation and test resync, with no consumer evidence asking for it.
>
> One rule follows from the stream choice, and has ONE home
> (`gda.headless.emit_failure`): a failed CHILD RUN's raw stderr is forwarded to gda's
> own stderr, EXCEPT when the human channel is about to print those very bytes as
> `diagnostics` — byte identity decides, so a curated or capped `diagnostics` keeps its
> tee, and under `--json` the tee is unconditional. Producers attach the stream to the
> `Failure` and never tee for themselves; #803 brought the last one that did — `scene
> preflight`, which reaches the launch primitive directly instead of through the shared
> pipeline — under the rule. Its own recorded exception is `gda script run`, which tees
> nothing because its success result IS the promoted `Raw run` (ADR-0031): there the
> child's streams are the operation's published output, not a diagnostic copy of it.

## `GdaError.code` registry

`GdaError.code` values are a public ABI for agents. Their authoritative source is
the Python registry in `src/gda/error_codes.py`; the table below mirrors that
source and is checked by tests. GDScript mirrors only the rows whose source is
`operation`, because only those codes can be reported by headless operations.

The `Meaning` column is pinned too (#701): it must match the registry's
`description` once markup and wrapping are normalized. A trailing parenthetical
that cites at least one ADR or issue — a `Phase N` label may ride along inside
it — is a citation rather than part of the code's meaning, so it is not compared.
Many rows here carry one, and some registry descriptions do too: that is allowed,
not a mistake to tidy away. A bare `(Phase N)` is *not* a citation and IS compared,
which is why the live rows below state their phase through the `Category` column
instead. `tests/test_error_registry.py` is the single home of that rule.

Each row carries the process `Exit Code` a shell consumer keys on. It is
per-code, not per-category: within `environment`, `binary_not_found` exits `127`
but `launch_timeout` exits `124`. The `exit_codes.py` registry defines the
values (`127`/`124` follow shell convention; `3`/`4`/`5` are the version,
operation, and parse codes the CLI assigns).

| Code | Category | Source | Exit Code | Meaning |
| --- | --- | --- | --- | --- |
| `binary_not_found` | `environment` | `runner` | `127` | The Godot binary could not be launched. |
| `launch_timeout` | `environment` | `runner` | `124` | Godot launched but did not return before the runner timeout; the envelope carries the run's captured partial output, the ceiling it reached and the elapsed wall clock. One command does not report it: `scene preflight` reports its own `timeout` status instead (#664). |
| `user_data_unwritable` | `environment` | `runner` | `127` | The log or user-data placement for the launch could not be made usable, so the launch was refused. |
| `unknown_command` | `usage` | `classifier` | `2` | gda has no such command; discover the surface with `gda schema` or `gda --help`. A recognized near miss also carries the supported invocation in the envelope's `hint`. |
| `unknown_option` | `usage` | `classifier` | `2` | The command exists but has no such option; read its options with `--help` or its input contract with `--schema`. A recognized near miss also carries the supported invocation in the envelope's `hint`. |
| `unsupported_version` | `version` | `version_gate` | `3` | The detected Godot version is below the supported minimum. |
| `engine_crashed` | `operation` | `classifier` | `4` | Godot terminated abnormally, such as by signal death. |
| `operation_failed` | `operation` | `classifier` | `4` | The engine or operation failed without a valid registered operation error envelope. |
| `usage_error` | `operation` | `operation` | `4` | The command was invoked incorrectly: the operation dispatcher received no operation name, or the CLI received `--params-json` together with the individual arguments (ADR-0015). |
| `unknown_operation` | `operation` | `operation` | `4` | The operation dispatcher received an unknown operation name. |
| `invalid_params` | `operation` | `operation` | `4` | Params do not match the command's contract: the operation dispatcher received non-object params, or a `--params-json` object was malformed or schema-invalid (ADR-0015). |
| `invalid_path` | `operation` | `operation` | `4` | A required path parameter is missing or invalid. |
| `invalid_root_type` | `operation` | `operation` | `4` | A requested Godot root node type cannot be instantiated as a `Node`. |
| `invalid_root_name` | `operation` | `operation` | `4` | A requested root node name is empty or would be rewritten by Godot. |
| `already_exists` | `operation` | `operation` | `4` | A create operation target already exists and will not be overwritten. |
| `save_failed` | `operation` | `operation` | `4` | A scene could not be packed or saved. |
| `delete_failed` | `operation` | `operation` | `4` | A file could not be removed from disk. |
| `file_changed_externally` | `operation` | `operation` | `4` | A read-modify-write operation's target file changed on disk between the read and the write, so the write was refused to avoid clobbering the external edit. |
| `project_not_found` | `operation` | `operation` | `4` | gda has no resolved Godot project usable for the requested target: an operation needed one and none was resolved, or an explicit `--project` was empty, or a `--project`/`$GDA_PROJECT` does not name a Godot project (no `project.godot`). |
| `target_outside_project` | `operation` | `classifier` | `4` | A requested target does not belong to the resolved Godot project, so gda refused before running the engine rather than resolving the target's `res://` references against the wrong root. gda does not derive a project from the target: pass `--project` naming the project that owns it, or name a target inside the resolved one (ADR-0006 amendment, #697). |
| `path_not_found` | `operation` | `operation` | `4` | A requested file does not exist. |
| `not_a_scene` | `operation` | `operation` | `4` | A requested file cannot be loaded as a `PackedScene`. |
| `parent_not_found` | `operation` | `operation` | `4` | A requested parent node path does not resolve to a node in the scene. |
| `invalid_node_type` | `operation` | `operation` | `4` | A requested node type is neither an instantiable `Node` class nor a registered `class_name`. |
| `invalid_node_name` | `operation` | `operation` | `4` | A requested node name is empty or would be rewritten by Godot. |
| `duplicate_node_name` | `operation` | `operation` | `4` | The parent node already has a child with the requested name. |
| `invalid_child_index` | `operation` | `operation` | `4` | A requested child insertion or move index is outside the valid sibling range. |
| `missing_dependency` | `operation` | `operation` | `4` | A scene's declared nodes vanished or degraded on load — an unresolvable instanced sub-scene, an unavailable node class, or a GDScript preload target that does not exist; re-saving would silently drop or downgrade scene data. |
| `uninstantiable_script` | `operation` | `operation` | `4` | A registered `class_name`'s script can no longer be loaded, compiled, or constructed, so it cannot be instantiated as a node or a resource. |
| `ambiguous_class_name` | `operation` | `operation` | `4` | A `class_name` is declared in more than one `.gd` script, so a request naming it (node add, resource create, or find-references) cannot resolve it to a single script; the conflicting script paths are named (ADR-0032). |
| `node_not_found` | `operation` | `operation` | `4` | A requested node path does not resolve to a node in the scene. |
| `cannot_target_root` | `operation` | `operation` | `4` | A structural edit targeted the scene root, which has no parent to be removed from, duplicated alongside, or reparented out of. |
| `cyclic_target` | `operation` | `operation` | `4` | The write would create a cycle: a node move targeted the node itself or one of its own descendants, or a scene instancing (node add --instance) targeted the host scene itself. |
| `unknown_property` | `operation` | `operation` | `4` | A requested property does not exist as a settable property on the target node or resource. |
| `uncoercible_value` | `operation` | `operation` | `4` | A supplied value cannot be coerced to the property's declared Godot type. |
| `expected_resource_path` | `operation` | `operation` | `4` | An Object-typed property was given a value that is not a `res://` resource path; assign an existing Resource by its `res://` path (ADR-0033, #363). |
| `not_a_resource` | `operation` | `operation` | `4` | A `res://` value for an Object-typed property does not load as a Resource (the path is missing or does not name a resource) (ADR-0033, #363). |
| `resource_type_mismatch` | `operation` | `operation` | `4` | A `res://` resource's type is incompatible with the Object-typed property's expected engine class (ADR-0033, #363). |
| `use_script_attach` | `operation` | `operation` | `4` | The `script` property is bound with `gda script attach` (which verifies the script compiles and its base type matches), not with `node set` / `resource set` (ADR-0033, #363). |
| `unsupported_property_type` | `operation` | `operation` | `4` | An Object-typed property expects a type `node set` / `resource set` cannot yet assign a `res://` resource to: a script `class_name`-typed property (deferred to the ADR-0032 resolver) or an Object property with no declared engine class (ADR-0033, #363). |
| `no_search_match` | `operation` | `operation` | `4` | A search-replace script edit found no occurrence of the search string. |
| `invalid_line_range` | `operation` | `operation` | `4` | A line-range script edit specified lines outside the script's bounds, or end before start. |
| `script_compile_failed` | `operation` | `operation` | `4` | A script does not compile, so the requested work could not proceed: `script attach` refuses to bind it to a node, and `script run` reports that the entry script (or a dependency it preloads) never ran (#651). |
| `script_not_found` | `operation` | `classifier` | `4` | A `script run` entry script does not exist in the project, so the engine never ran it — it still exits 0, and gda reads the failure from stderr (#651). |
| `script_failed` | `operation` | `classifier` | `4` | A `script run --strict` script ran to completion and chose a non-zero exit status; strict mode maps that opted-in failure onto the uniform error envelope. Never reported without `--strict` (ADR-0031 amendment, #651). |
| `script_aborted` | `operation` | `classifier` | `4` | A `script run` was ended early, before its `--timeout`: a script error appeared on stderr, the caller's declared `--completion-marker` did not, and the run then went silent. Reported only when `--completion-marker` is declared (ADR-0031 amendment, #655). |
| `incompatible_script_type` | `operation` | `operation` | `4` | A script compiles but its base type is incompatible with the requested use: `script attach`'s target node type, or `script run`'s requirement that a one-shot entry script extend `SceneTree`/`MainLoop` (#651). |
| `signal_not_found` | `operation` | `operation` | `4` | A requested signal does not exist on the source node. |
| `already_connected` | `operation` | `operation` | `4` | A signal is already connected to the target node's method. |
| `connection_not_found` | `operation` | `operation` | `4` | A requested signal-to-method connection does not exist on the source node. |
| `invalid_resource_type` | `operation` | `operation` | `4` | A requested resource type cannot be instantiated as a `Resource`. |
| `export_presets_not_found` | `operation` | `operation` | `4` | The project has no export_presets.cfg, so it defines no export presets. |
| `export_preset_not_found` | `operation` | `operation` | `4` | No export preset with the requested name exists in export_presets.cfg. |
| `export_path_unset` | `operation` | `classifier` | `4` | An export run has no destination — neither a `--output` override nor a configured `export_path` (#170). |
| `export_templates_missing` | `operation` | `classifier` | `4` | A release/debug export needs the export templates for the running engine version, which are not installed; `pack` needs no platform templates and is exempt (#170). |
| `export_output_parent_failed` | `operation` | `classifier` | `4` | An export run could not create the output parent directory before native export (#402). |
| `stdout_spill_failed` | `operation` | `classifier` | `4` | A `script run`'s stdout exceeded the cap but the complete-stream spill file could not be written, so the bounded result cannot be delivered (#665). |
| `export_failed` | `operation` | `classifier` | `4` | A native Godot export run failed (the engine reported the export did not complete). |
| `invalid_uid` | `operation` | `operation` | `4` | A requested `uid://` value is not a syntactically valid resource UID. |
| `unknown_uid` | `operation` | `operation` | `4` | A syntactically valid resource UID is not registered in the engine's UID cache. |
| `no_uid_assigned` | `operation` | `operation` | `4` | A resource path exists but has no UID assigned in the engine's UID cache. |
| `unknown_setting` | `operation` | `operation` | `4` | A requested project setting does not exist in the project's ProjectSettings. |
| `invalid_target` | `operation` | `operation` | `4` | A project find-references target is empty or not a valid `res://` path or `class_name`. |
| `invalid_key` | `operation` | `operation` | `4` | An input-action key could not be resolved to a Godot keycode (unknown key name or non-positive keycode). |
| `contract_violation` | `parse` | `parser` | `5` | The process claimed success but violated the structured-output contract. |
| `tree_too_deep` | `parse` | `classifier` | `5` | The engine emitted a valid result tree that nests past gda's recursion limit; the payload is contract-conformant, the limit is wrapper-side (shares the `parse` exit code; the `code` distinguishes it from `contract_violation`). |
| `daemon_not_running` | `live` | `classifier` | `6` | A live command found no running gda-daemon for the project; start one with `gda daemon start` (Phase 2, ADR-0017 / ADR-0021). |
| `engine_session_not_running` | `live` | `classifier` | `6` | The daemon is running but holds no live engine session to serve the live operation. |
| `engine_disconnected` | `live` | `classifier` | `6` | The engine session disconnected before the live operation returned — the game crashed or the harness connection dropped. |
| `live_timeout` | `live` | `classifier` | `6` | A live operation did not return from the engine session before the daemon's timeout. The session is discarded: its reply is no longer attributable, so the next operation relaunches it and runtime state does not survive. |
| `daemon_running` | `live` | `classifier` | `6` | A daemon-lifecycle command was refused because a gda-daemon is running for the project; stop it first with `gda daemon stop` (Phase 2, #225). |
| `daemon_already_running` | `live` | `classifier` | `6` | A `gda daemon start --scene` was refused because a gda-daemon is already running for the project; `--scene` only takes effect at start, so stop it with `gda daemon stop` then start again with `--scene` (Phase 2, #278). |
| `live_node_not_found` | `live` | `classifier` | `6` | A live game operation's node path does not resolve to a node in the running scene tree (Phase 2, #220). |
| `live_not_control` | `live` | `classifier` | `6` | A live game rect operation targeted a running node that is not a Control (Phase 2, #419). |
| `live_unknown_property` | `live` | `classifier` | `6` | A live game get or set targeted a property name the running node does not expose as an addressable runtime, storage, or attached-script property (Phase 2, #220, #422). |
| `live_uncoercible_value` | `live` | `classifier` | `6` | A live game set value cannot be coerced to the addressed runtime property's or script variable's Godot type (Phase 2, #220, #422). |
| `live_unknown_method` | `live` | `classifier` | `6` | A live game call named a method the addressed running node does not have (Phase 2, #673). |
| `live_method_not_allowlisted` | `live` | `classifier` | `6` | A live game call named a method the addressed running node has but its attached-script chain never declared gda-callable (Phase 2, #673, ADR-0041). |
| `live_invalid_call_args` | `live` | `classifier` | `6` | A live game call supplied arguments the declared method cannot take: a count outside its accepted range, or a value the declared parameter type cannot convert from (Phase 2, #673). |
| `live_log_unavailable` | `live` | `classifier` | `6` | A live engine session was launched but its diagnostics log file is missing or unreadable, so `gda diag` cannot read the running game's errors/output (Phase 2, #224). |
| `live_scene_not_found` | `live` | `classifier` | `6` | A `gda daemon start --scene` selector did not load: the launched session ran a different scene (Godot silently falls back to main_scene for a missing/invalid path or UID), verified by the harness at launch — gda never falls back (Phase 2, #278). |
| `live_perf_node_not_found` | `live` | `classifier` | `6` | A live perf monitor's node path does not resolve to a node in the running scene tree (Phase 2, #223). |
| `live_perf_property_not_found` | `live` | `classifier` | `6` | A live perf monitor targeted a property the running node does not expose for reading (Phase 2, #223). |
| `live_perf_signal_not_found` | `live` | `classifier` | `6` | A live perf monitor targeted a signal the running node does not declare (Phase 2, #223). |
| `live_invalid_key` | `live` | `classifier` | `6` | A live input key event named a key the engine could not resolve to a keycode (Phase 2, #221). |
| `live_unknown_action` | `live` | `classifier` | `6` | A live input action targeted an action the running game's InputMap does not declare (Phase 2, #221). |
| `live_invalid_event_spec` | `live` | `classifier` | `6` | A live input sequence event has a type the harness does not recognize (Phase 2, #221). |
| `live_predicate_unmet` | `live` | `classifier` | `6` | A live `screen capture` predicate (`--await-*`) did not hold within its declared frame bound (Phase 2, #661). |
| `live_display_unavailable` | `live` | `classifier` | `6` | A live `screen` capture ran on a headless engine session (the dummy DisplayServer cannot read pixels); start the daemon windowed with `gda daemon start --windowed` (Phase 2, #222). |
| `live_unsupported_platform` | `environment` | `classifier` | `127` | Live operations require a UNIX platform (macOS/Linux); they use Unix domain sockets, which are unavailable here. Phase-1 headless is unaffected (Phase 2, ADR-0021). |
| `live_windowed_unavailable` | `environment` | `classifier` | `127` | A windowed Engine session was requested (`gda daemon start --windowed`) but the host has no usable DisplayServer (no on-console GUI session / no `$DISPLAY`), so the session cannot come up; refused before spawning Godot (Phase 2, #345). |
| `live_windowed_permission_denied` | `environment` | `classifier` | `127` | A windowed Engine session was requested (`gda daemon start --windowed`) but this process is denied the window-server lookup (e.g. a sandbox), so gda cannot tell whether the host has one; re-run outside the restriction to find out rather than recording the host as display-less (Phase 2, #667). |
| `harness_install_permission_denied` | `environment` | `classifier` | `127` | The gda harness install (`gda daemon start` — including a repeat start's self-sync — or `gda daemon install`) was REFUSED access to the project's filesystem: the OS denied the permission, or the filesystem is read-only. The message names the path that was refused, and any partial write is rolled back where the filesystem still allows it. A filesystem failure that is NOT a refusal — a full disk, a missing or malformed path, an I/O error — does not carry this code; it propagates as before: after the same rollback when a snapshot exists, and directly when the failure came from the pre-install snapshot read itself, which has written nothing to roll back. (Phase 2, #700) |

> **Outcome (2026-08-31, #716 / #717) — `launch_timeout` keeps its category, and a
> timed-out run's captured stream stays advisory.** Both questions are about the one
> row above, and #714 is what reopened them: it put the run's captured partial output,
> the ceiling it reached and its elapsed wall clock on the envelope for EVERY
> launch-backed channel. They are decided once, here, because this row is where all
> four are governed — the sentinel dispatch, the native export and the `resource
> import` pass through the shared builder, and `script run` through its own builder
> under the same code.
>
> - **The captured stream does not re-verdict (#716).** A recognized entry-load error
>   inside the capture — one that would satisfy a #651 verdict on a run that had
>   finished — stays an advisory diagnostic under `launch_timeout`; the code is
>   unchanged. Only one of the two facts is gda's own: it OBSERVED that it stopped
>   waiting, and would have to INFER the entry-load cause from bytes the child happened
>   to have written by then. That inference is unsound by construction — the capture is
>   tail-capped and was cut mid-flight, so a recognized line can be an earlier phase's
>   error the run survived, or half a line — and the misattribution would be silent,
>   which is the worst shape for an agent branching on `code`. The need a re-verdict
>   was meant to serve is the cause as DATA, and #687 owns that: typed evidence on the
>   envelope keeps the honest verdict AND carries what the channel can prove instead of
>   the capture. Its reach is BOUNDED, and this decision does not assume otherwise: a
>   PARSED cause exists only where a channel parses one, which today is `script run`
>   alone. The other three carry how the run ended — the ceiling it reached and its
>   elapsed clock — and keep the capture in `diagnostics` as prose, which is what the
>   advisory rule above governs. What this decision needs from #687 is that the capture
>   stops being the only evidence, not that every channel end up with the same evidence.
>   The failure message states the rule in one clause, so a caller reading the
>   diagnostics does not re-verdict on gda's behalf either.
> - **The category stays `environment` (#717).** Reaching a ceiling the caller chose is
>   a normal outcome of probing a slow suite, and `environment` points an agent at
>   retry / reinstall / another-host remedies — but the same code also fires for a
>   genuinely environmental hang, so no other category is true of the whole row, and
>   `category` is public ABI every consumer keys on. A second code for the
>   caller-configured case would double the branch surface to carry a provenance fact
>   that does not change what to do next; that fact, if it is ever wanted as data,
>   belongs on #687's evidence object. What was actually wrong was the REMEDIATION
>   ORDER, so the message now leads with the caller's remedy — read the capture, then
>   raise the ceiling — and puts binary/host suspicion last, under the condition that
>   earns it (a capture showing the engine never started). `--timeout` is named WITH
>   its qualifier, because of the shared builder's three channels only `resource
>   import` exposes it: the sentinel's 60s and the export's 600s are gda's own, fixed.
>   No registry, category, exit-code or schema change follows — the equality-pinned
>   registry test is untouched, which is what proves the scope.
>
> `scene preflight` is an exception to neither half: it does not report this code at
> all. Its bound IS its answer, recorded in the 2026-08-19 (#664) scope note above —
> read that note rather than re-deriving the difference by diffing the two commands.

## Considered options

- **Sentinel-delimited JSON on stdout** (chosen) — simplest, streamable, and the
  unique marker isolates the result from engine noise. Generalises to the
  per-message protocol the daemon will need in Phase 2.
- **Separate `gda-error:<code>:` marker on stderr for operation failures** —
  rejected; stderr is also where engine and script diagnostics appear, so parsing
  it for stable codes is spoofable. Regex capture also truncates multiline
  messages. Success and failure should share one structured channel instead.
- **Result file always** — strongest isolation from stdout noise, but adds temp-file
  lifecycle and cannot stream; kept only as the large-payload escape hatch.
- **Raw passthrough** (like `godot-mcp`) — rejected; it abandons the structured-output
  goal.

## Consequences

- Every GDScript operation must discipline its logging to stderr; emitting to stdout
  outside the sentinels is a contract violation that corrupts results.
- The sentinel strings are part of the wire contract between `gda` and its GDScript
  payloads, and changing them is a breaking change.
- Adding or changing a `GdaError.code` requires updating the Python registry, this
  ADR's registry table, and any GDScript operation-code mirror. Tests must reject
  drift between those copies.
- `gda <command> --schema` describes the success result model under its `output`
  key. Whether command schemas should include the failure envelope was resolved in
  #43: `--schema` now also carries a uniform `error` key holding this ADR's failure
  envelope (the shared `GdaErrorEnvelope` schema), kept separate from `output` so the
  success result and the failure envelope stay distinct channels. See ADR-0004.
