"""Authoritative registry of public ``GdaError.code`` values.

The registry is the machine-readable companion to ADR-0002's table. Every code
emitted in a public ``GdaError`` must be declared here.

**Editing a ``description``.** Its wording is pinned against that ADR's ``Meaning``
column, so a change here needs the same change there (#701). What the pin
normalizes away — markup, wrapping, and a trailing ADR/issue citation — is stated
with its reasoning in ``tests/test_error_registry.py``, the single home of that
rule.

**What ``source`` means.** It names a code's *authoritative origin channel* — the
layer that defines the failure and owns reporting it — and it governs **GDScript
mirror membership**: ``operations.gd`` declares exactly the ``operation``-source
codes, because those are the ones a headless operation may report back through
the ADR-0002 sentinel.

It is **not an exclusive emitter list**. The Python classifier may additionally
assign any registered code whose semantics match the failure it recognized —
including an ``operation``-source one — when it learns of that failure from the
engine's own output rather than from a sentinel. This predates the
classifier-side reuse in #651: ``script_path_invalid_failure`` has long minted
operation-source ``invalid_path`` from the CLI. Two consequences worth stating
because they have been misread: reuse-vs-mint is decided by **semantic match**,
never by ``source``; and classifier reuse adds no member and removes none, so the
mirror derivation is untouched by it.
"""

from dataclasses import dataclass
from enum import Enum

from gda.exit_codes import (
    EXIT_LIVE,
    EXIT_NOT_FOUND,
    EXIT_OPERATION,
    EXIT_PARSE,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    EXIT_VERSION,
)
from gda.models import ErrorCategory


class ErrorCodeSource(str, Enum):
    """A code's authoritative origin channel — see the module docstring.

    The layer that defines the failure and owns reporting it, and the key the
    GDScript mirror's membership is derived from. NOT an exclusive emitter list:
    the Python classifier may also assign a code whose semantics match a failure
    it recognized from the engine's output.
    """

    RUNNER = "runner"
    CLASSIFIER = "classifier"
    OPERATION = "operation"
    PARSER = "parser"
    VERSION_GATE = "version_gate"


@dataclass(frozen=True)
class ErrorCodeSpec:
    """One public ``GdaError.code`` registry entry.

    A single row fully defines a code's public ABI: its coarse ``category``, the
    process ``exit_code`` a shell consumer keys on (per-code, not per-category:
    within ENVIRONMENT, ``binary_not_found`` exits 127 but ``launch_timeout``
    exits 124), the ``source`` that authoritatively owns it — an origin channel
    and the mirror-membership key, not an exclusive emitter list (see the module
    docstring) — and its ``description``. Failure construction derives
    ``category`` and ``exit_code`` from here, so it no longer restates either at
    the call site — both come from the row (ADR-0002, #141).
    """

    code: str
    category: ErrorCategory
    exit_code: int
    source: ErrorCodeSource
    description: str


ERROR_CODES: tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        "binary_not_found",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.RUNNER,
        "The Godot binary could not be launched.",
    ),
    ErrorCodeSpec(
        "launch_timeout",
        ErrorCategory.ENVIRONMENT,
        EXIT_TIMEOUT,
        ErrorCodeSource.RUNNER,
        # The scope caveat is not decoration (#701): `scene preflight` owns a
        # wall-clock bound of its own and reports exceeding it as a `timeout`
        # STATUS on a successful result, so an agent that branches on this code
        # alone would never see that command's timeout.
        "Godot launched but did not return before the runner timeout; the envelope "
        "carries the run's captured partial output, the ceiling it reached and "
        "the elapsed wall clock. One command does not report it: `scene "
        "preflight` reports its own `timeout` status instead.",
    ),
    ErrorCodeSpec(
        "user_data_unwritable",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.RUNNER,
        # Deliberately about the PLACEMENT, not about Godot's own directory: the
        # same code covers a private temporary log target that could not be created
        # (where Godot's location may be perfectly writable) and a redirected root
        # whose derived data path is unusable. Naming only the latter sent readers
        # to fix the wrong directory; the diagnostics name which one it was.
        "The log or user-data placement for the launch could not be made usable, "
        "so the launch was refused.",
    ),
    # The USAGE category (#670): gda could not resolve WHAT was asked for, so no
    # operation was ever identified — the stage before every other code here. Both
    # rows are classifier-source (the CLI decides them; no GDScript operation can
    # report one, so neither is mirrored) and both exit 2, the code every CLI parser
    # already uses for a usage error: gda's structured refusal is that same failure
    # reported better, not a different one, so the exit an agent already keys on is
    # unchanged. They are kept apart from each other because the remedy differs — an
    # unknown COMMAND sends the caller to `gda schema` / `gda --help`, an unknown
    # OPTION to that command's own `--help` / `--schema`.
    ErrorCodeSpec(
        "unknown_command",
        ErrorCategory.USAGE,
        EXIT_USAGE,
        ErrorCodeSource.CLASSIFIER,
        "gda has no such command; discover the surface with `gda schema` or "
        "`gda --help`. A recognized near miss also carries the supported "
        "invocation in the envelope's `hint`.",
    ),
    ErrorCodeSpec(
        "unknown_option",
        ErrorCategory.USAGE,
        EXIT_USAGE,
        ErrorCodeSource.CLASSIFIER,
        "The command exists but has no such option; read its options with "
        "`--help` or its input contract with `--schema`. A recognized near miss "
        "also carries the supported invocation in the envelope's `hint`.",
    ),
    ErrorCodeSpec(
        "unsupported_version",
        ErrorCategory.VERSION,
        EXIT_VERSION,
        ErrorCodeSource.VERSION_GATE,
        "The detected Godot version is below the supported minimum.",
    ),
    ErrorCodeSpec(
        "engine_crashed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "Godot terminated abnormally, such as by signal death.",
    ),
    ErrorCodeSpec(
        "operation_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "The engine or operation failed without a valid registered operation error envelope.",
    ),
    ErrorCodeSpec(
        "usage_error",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The command was invoked incorrectly: the operation dispatcher received no "
        "operation name, or the CLI received --params-json together with the "
        "individual arguments (ADR-0015).",
    ),
    ErrorCodeSpec(
        "unknown_operation",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The operation dispatcher received an unknown operation name.",
    ),
    ErrorCodeSpec(
        "invalid_params",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "Params do not match the command's contract: the operation dispatcher "
        "received non-object params, or a --params-json object was malformed or "
        "schema-invalid (ADR-0015).",
    ),
    ErrorCodeSpec(
        "invalid_path",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A required path parameter is missing or invalid.",
    ),
    ErrorCodeSpec(
        "invalid_root_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested Godot root node type cannot be instantiated as a Node.",
    ),
    ErrorCodeSpec(
        "invalid_root_name",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested root node name is empty or would be rewritten by Godot.",
    ),
    ErrorCodeSpec(
        "already_exists",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A create operation target already exists and will not be overwritten.",
    ),
    ErrorCodeSpec(
        "save_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A scene could not be packed or saved.",
    ),
    ErrorCodeSpec(
        "delete_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A file could not be removed from disk.",
    ),
    ErrorCodeSpec(
        "file_changed_externally",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A read-modify-write operation's target file changed on disk between the read and the write, so the write was refused to avoid clobbering the external edit.",
    ),
    ErrorCodeSpec(
        "project_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "gda has no resolved Godot project usable for the requested target: an operation needed one and none was resolved, or an explicit --project was empty, or a --project/$GDA_PROJECT does not name a Godot project (no project.godot).",
    ),
    # The sibling `project_not_found` carried until #697: a project WAS resolved,
    # it just does not own the target. It is CLASSIFIER-source and so not
    # GDScript-mirrored, because ADR-0006 keeps project resolution — and therefore
    # this refusal — entirely CLI-side; no operation can report it.
    ErrorCodeSpec(
        "target_outside_project",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A requested target does not belong to the resolved Godot project, so gda"
        " refused before running the engine rather than resolving the target's"
        " res:// references against the wrong root. gda does not derive a project"
        " from the target: pass --project naming the project that owns it, or name"
        " a target inside the resolved one (ADR-0006 amendment, #697).",
    ),
    ErrorCodeSpec(
        "path_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested file does not exist.",
    ),
    ErrorCodeSpec(
        "not_a_scene",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested file cannot be loaded as a PackedScene.",
    ),
    ErrorCodeSpec(
        "parent_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested parent node path does not resolve to a node in the scene.",
    ),
    ErrorCodeSpec(
        "invalid_node_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node type is neither an instantiable Node class nor a registered class_name.",
    ),
    ErrorCodeSpec(
        "invalid_node_name",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node name is empty or would be rewritten by Godot.",
    ),
    ErrorCodeSpec(
        "duplicate_node_name",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The parent node already has a child with the requested name.",
    ),
    ErrorCodeSpec(
        "invalid_child_index",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested child insertion or move index is outside the valid sibling range.",
    ),
    ErrorCodeSpec(
        "missing_dependency",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A scene's declared nodes vanished or degraded on load — an"
        " unresolvable instanced sub-scene, an unavailable node class, or a"
        " GDScript preload target that does not exist; re-saving would silently"
        " drop or downgrade scene data.",
    ),
    ErrorCodeSpec(
        "uninstantiable_script",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A registered class_name's script can no longer be loaded, compiled,"
        " or constructed, so it cannot be instantiated as a node or a resource.",
    ),
    ErrorCodeSpec(
        "ambiguous_class_name",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A class_name is declared in more than one .gd script, so a request naming"
        " it (node add, resource create, or find-references) cannot resolve it to a"
        " single script; the conflicting script paths are named (ADR-0032).",
    ),
    ErrorCodeSpec(
        "node_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node path does not resolve to a node in the scene.",
    ),
    ErrorCodeSpec(
        "cannot_target_root",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A structural edit targeted the scene root, which has no parent to be"
        " removed from, duplicated alongside, or reparented out of.",
    ),
    ErrorCodeSpec(
        "cyclic_target",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The write would create a cycle: a node move targeted the node itself"
        " or one of its own descendants, or a scene instancing (node add"
        " --instance) targeted the host scene itself.",
    ),
    ErrorCodeSpec(
        "unknown_property",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested property does not exist as a settable property on the target node or resource.",
    ),
    ErrorCodeSpec(
        "uncoercible_value",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A supplied value cannot be coerced to the property's declared Godot type.",
    ),
    # Object-typed property assignment via a res:// resource reference (ADR-0033,
    # #363): node set / resource set assign an EXISTING Resource, referenced by a
    # res:// path, to an Object-typed property that expects a Resource (sub)class.
    # These five distinguish the failure modes from the generic uncoercible_value —
    # each is an operation-source code, so all are GDScript-mirrored in operations.gd.
    ErrorCodeSpec(
        "expected_resource_path",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "An Object-typed property was given a value that is not a res:// resource "
        "path; assign an existing Resource by its res:// path.",
    ),
    ErrorCodeSpec(
        "not_a_resource",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A res:// value for an Object-typed property does not load as a Resource "
        "(the path is missing or does not name a resource).",
    ),
    ErrorCodeSpec(
        "resource_type_mismatch",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A res:// resource's type is incompatible with the Object-typed property's "
        "expected engine class.",
    ),
    ErrorCodeSpec(
        "use_script_attach",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The script property is bound with `gda script attach` (which verifies the "
        "script compiles and its base type matches), not with node set / resource set.",
    ),
    ErrorCodeSpec(
        "unsupported_property_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "An Object-typed property expects a type node set / resource set cannot yet "
        "assign a res:// resource to: a script class_name-typed property (deferred to "
        "the ADR-0032 resolver) or an Object property with no declared engine class.",
    ),
    ErrorCodeSpec(
        "no_search_match",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A search-replace script edit found no occurrence of the search string.",
    ),
    ErrorCodeSpec(
        "invalid_line_range",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A line-range script edit specified lines outside the script's bounds, or end before start.",
    ),
    ErrorCodeSpec(
        "script_compile_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A script does not compile, so the requested work could not proceed: "
        "`script attach` refuses to bind it to a node, and `script run` reports "
        "that the entry script (or a dependency it preloads) never ran.",
    ),
    # `script run`'s two NEW verdict codes (#651, ADR-0031 amendment). Both are
    # decided by gda from the engine's stderr AFTER the run, so both are
    # CLASSIFIER-source and NOT GDScript-mirrored — the entry script is the user's
    # own and emits no ADR-0002 sentinel.
    #
    # Reuse-vs-mint is decided by SEMANTIC MATCH, not by `source` (the module
    # docstring is the single home of what `source` does and does not mean). This
    # change reuses operation-source `script_compile_failed` and
    # `incompatible_script_type` from the classifier, because `script run` hits the
    # very conditions they name — a script that does not compile, and one whose
    # base type is wrong for the requested use (ADR-0002 — reuse the code,
    # discriminate via the message).
    #
    # `script_not_found` is minted rather than reusing `path_not_found` for the
    # opposite reason: the MEANINGS differ. `path_not_found` is "a file the
    # operation was asked to act on is absent" — a filesystem fact about an
    # operand. This is "the engine could not load the entry script, so the run
    # never happened" — a fact about the run itself, which an agent branches on
    # differently (re-check the path vs. abandon the result entirely).
    ErrorCodeSpec(
        "script_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A `script run` entry script does not exist in the project, so the engine "
        "never ran it — it still exits 0, and gda reads the failure from stderr.",
    ),
    ErrorCodeSpec(
        "script_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A `script run --strict` script ran to completion and chose a non-zero exit "
        "status; strict mode maps that opted-in failure onto the uniform error "
        "envelope. Never reported without --strict (ADR-0031).",
    ),
    # `script run`'s early-abort verdict (#655, dogfooding GDA-DF-012). Minted
    # rather than reused, because no registered code names this condition:
    #
    # - `launch_timeout` says "Godot did not return before the timeout". Here gda
    #   DECIDED not to wait — the timeout was never reached — so reporting it would
    #   be untrue, and would hide the very distinction the abort exists to make.
    # - `script_failed` says "the script ran to completion and chose a non-zero
    #   status", is documented as never reported without `--strict`, and leads an
    #   agent to read an exit status. Here the script never completed and there is
    #   no status to read; the remedy is the error it died on.
    # - `script_compile_failed` / `script_not_found` say the entry never LOADED.
    #   Here it loaded and ran, then hit an error partway.
    #
    # CLASSIFIER-source and so NOT GDScript-mirrored, like the rest of `script
    # run`'s verdicts: the entry script is the user's own and emits no ADR-0002
    # sentinel, so gda decides this from the engine's error stream.
    ErrorCodeSpec(
        "script_aborted",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A `script run` was ended early, before its --timeout: a script error "
        "appeared on stderr, the caller's declared --completion-marker did not, "
        "and the run then went silent. Reported only when --completion-marker is "
        "declared (#655).",
    ),
    ErrorCodeSpec(
        "incompatible_script_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A script compiles but its base type is incompatible with the requested "
        "use: `script attach`'s target node type, or `script run`'s requirement "
        "that a one-shot entry script extend SceneTree/MainLoop.",
    ),
    ErrorCodeSpec(
        "signal_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested signal does not exist on the source node.",
    ),
    ErrorCodeSpec(
        "already_connected",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A signal is already connected to the target node's method.",
    ),
    ErrorCodeSpec(
        "connection_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested signal-to-method connection does not exist on the source node.",
    ),
    ErrorCodeSpec(
        "invalid_resource_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested resource type cannot be instantiated as a Resource.",
    ),
    ErrorCodeSpec(
        "export_presets_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "The project has no export_presets.cfg, so it defines no export presets.",
    ),
    ErrorCodeSpec(
        "export_preset_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "No export preset with the requested name exists in export_presets.cfg.",
    ),
    ErrorCodeSpec(
        "export_path_unset",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        # Both producing conditions, not just the configured one (#701): the
        # destination is `--output` if given, else the preset's `export_path`, so
        # the failure needs BOTH to be absent — a reader told only about
        # `export_path` would not know the override exists.
        "An export run has no destination — neither a `--output` override nor a "
        "configured `export_path`.",
    ),
    ErrorCodeSpec(
        "export_templates_missing",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        # Scoped to the modes that actually need templates (#701): `pack` produces
        # project data only, so the preflight skips the check for it. "An export
        # run" claimed the code can fire for a mode it never fires for.
        "A release/debug export needs the export templates for the running engine "
        "version, which are not installed; `pack` needs no platform templates and "
        "is exempt.",
    ),
    ErrorCodeSpec(
        "export_output_parent_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "An export run could not create the output parent directory before native export.",
    ),
    ErrorCodeSpec(
        "stdout_spill_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A script run's stdout exceeded the cap but the complete-stream spill "
        "file could not be written, so the bounded result cannot be delivered.",
    ),
    ErrorCodeSpec(
        "export_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "A native Godot export run failed (the engine reported the export did not complete).",
    ),
    ErrorCodeSpec(
        "invalid_uid",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested uid:// value is not a syntactically valid resource UID.",
    ),
    ErrorCodeSpec(
        "unknown_uid",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A syntactically valid resource UID is not registered in the engine's UID cache.",
    ),
    ErrorCodeSpec(
        "no_uid_assigned",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A resource path exists but has no UID assigned in the engine's UID cache.",
    ),
    ErrorCodeSpec(
        "unknown_setting",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested project setting does not exist in the project's ProjectSettings.",
    ),
    ErrorCodeSpec(
        "invalid_target",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A project find-references target is empty or not a valid res:// path or class_name.",
    ),
    ErrorCodeSpec(
        "invalid_key",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "An input-action key could not be resolved to a Godot keycode (unknown key name or non-positive keycode).",
    ),
    ErrorCodeSpec(
        "contract_violation",
        ErrorCategory.PARSE,
        EXIT_PARSE,
        ErrorCodeSource.PARSER,
        "The process claimed success but violated the structured-output contract.",
    ),
    ErrorCodeSpec(
        "tree_too_deep",
        ErrorCategory.PARSE,
        EXIT_PARSE,
        ErrorCodeSource.CLASSIFIER,
        "The engine emitted a valid result tree that nests past gda's recursion"
        " limit; the payload is contract-conformant, the limit is wrapper-side"
        " (shares the `parse` exit code; the `code` distinguishes it from"
        " `contract_violation`).",
    ),
    # Phase-2 live execution channel (ADR-0017, ADR-0021). Classifier-source —
    # surfaced by the daemon IPC client / the daemon, never by a headless
    # operation — so they are NOT GDScript-mirrored. They share the EXIT_LIVE
    # exit; the code tells the failure modes apart.
    ErrorCodeSpec(
        "daemon_not_running",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live command found no running gda-daemon for the project; start one"
        " with `gda daemon start`.",
    ),
    ErrorCodeSpec(
        "engine_session_not_running",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "The daemon is running but holds no live engine session to serve the"
        " live operation.",
    ),
    ErrorCodeSpec(
        "engine_disconnected",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "The engine session disconnected before the live operation returned —"
        " the game crashed or the harness connection dropped.",
    ),
    ErrorCodeSpec(
        "live_timeout",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live operation did not return from the engine session before the"
        " daemon's timeout. The session is discarded: its reply is no longer"
        " attributable, so the next operation relaunches it and runtime state"
        " does not survive.",
    ),
    # The harness-lifecycle refusal (#225, ADR-0018): `gda daemon uninstall`
    # removes the harness autoload + files, which would yank the autoload out from
    # under a live engine session the daemon is holding — so it refuses while a
    # daemon is running. Same shape as the other daemon-channel LIVE codes:
    # LIVE-category, classifier-source (the uninstall recipe emits it, not a
    # headless operation), exit EXIT_LIVE; NOT GDScript-mirrored.
    ErrorCodeSpec(
        "daemon_running",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A daemon-lifecycle command was refused because a gda-daemon is running"
        " for the project; stop it first with `gda daemon stop`.",
    ),
    # The `daemon start --scene` refusal (#278 review): `--scene` only takes effect
    # at daemon start, so requesting it against a daemon that is already running is a
    # typed refusal rather than a silent no-op that ignores the chosen scene. Same
    # daemon-channel shape: LIVE-category, classifier-source (the start recipe emits
    # it), exit EXIT_LIVE; NOT GDScript-mirrored.
    ErrorCodeSpec(
        "daemon_already_running",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A `gda daemon start --scene` was refused because a gda-daemon is already"
        " running for the project; `--scene` only takes effect at start, so stop it"
        " with `gda daemon stop` then start again with `--scene`.",
    ),
    # Per live-operation failures the gda harness reports in-band (#220). Harness
    # op-errors arrive with exit_code 0 (the daemon relays the sentinel verbatim),
    # so each MUST be a LIVE-category code for ``classify_live`` to map it before
    # the shared decision tree misroutes an exit-0 error envelope to
    # ``contract_violation``. CLASSIFIER-source — surfaced via the live channel,
    # not GDScript-mirrored by operations.gd — so the operations.gd mirror test is
    # unaffected; a separate test mirrors them against the harness consts.
    ErrorCodeSpec(
        "live_node_not_found",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game operation's node path does not resolve to a node in the running scene tree.",
    ),
    ErrorCodeSpec(
        "live_not_control",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game rect operation targeted a running node that is not a Control.",
    ),
    ErrorCodeSpec(
        "live_unknown_property",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game get or set targeted a property name the running node does not expose as an addressable runtime, storage, or attached-script property.",
    ),
    ErrorCodeSpec(
        "live_unknown_method",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game call named a method the addressed running node does not have.",
    ),
    ErrorCodeSpec(
        "live_method_not_allowlisted",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game call named a method the addressed running node has but its attached-script chain never declared gda-callable.",
    ),
    ErrorCodeSpec(
        "live_invalid_call_args",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game call supplied arguments the declared method cannot take: a count outside its accepted range, or a value the declared parameter type cannot convert from.",
    ),
    ErrorCodeSpec(
        "live_uncoercible_value",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live game set value cannot be coerced to the addressed runtime property's or script variable's Godot type.",
    ),
    # `gda diag` is a daemon-served live op (#224): the daemon reads the Session log
    # it launched the engine with (`--log-file`) and serves diagnostics from it,
    # even after the session process dies. This names the one new failure — a
    # session WAS launched but its log file is missing/unreadable. An empty log is
    # an empty result, not this error. CLASSIFIER-source (the daemon emits it, not
    # the harness), so it is NOT GDScript-mirrored.
    ErrorCodeSpec(
        "live_log_unavailable",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live engine session was launched but its diagnostics log file is missing"
        " or unreadable, so `gda diag` cannot read the running game's errors/output.",
    ),
    # `gda daemon start --scene <path|UID>` boots the session on a CHOSEN scene
    # (#278, ADR-0017 amendment). A missing/non-existent selector must surface this
    # TYPED failure rather than silently falling back to the project's main_scene.
    # The harness verifies the ACTUALLY-loaded scene against the requested selector
    # at launch (the only way to catch a bad uid, which Godot silently replaces with
    # main_scene); a mismatch is surfaced by the daemon as this code. CLASSIFIER-
    # source (the daemon mints it from the harness verification frame), so it is NOT
    # GDScript-mirrored.
    ErrorCodeSpec(
        "live_scene_not_found",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A `gda daemon start --scene` selector did not load: the launched session ran"
        " a different scene (Godot silently falls back to main_scene for a"
        " missing/invalid path or UID), verified by the harness at launch — gda never"
        " falls back.",
    ),
    # A session launch with NOTHING to run (#829): the project's
    # `application/run/main_scene` is empty and no `--scene` selector was given.
    # Godot would print "Can't run project: no main scene defined" and then call
    # OS::alert() unconditionally — on macOS a native modal that ignores --headless
    # and blocks until dismissed or killed — so gda refuses BEFORE spawning, at the
    # `daemon start` fail-fast and again at the daemon's authoritative launch
    # boundary. Same LIVE / exit-6 bucket as `live_scene_not_found` (the session's
    # scene cannot be run), classifier-source, NOT GDScript-mirrored.
    ErrorCodeSpec(
        "live_main_scene_undefined",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "The conservative file precheck determined that the project's"
        " `application/run/main_scene` is empty and no `--scene` selector was given;"
        " refused before daemon or Engine session launch to avoid Godot's native"
        " alert on macOS, even headless.",
    ),
    # The sibling verdict (#829): the main scene IS declared, as the `uid://` the
    # editor writes since Godot 4.4, but the checkout was never imported so the
    # engine has no UID cache to resolve it through (`main/main.cpp`: no
    # uid_cache.bin under the project data directory) — the same unconditional
    # alert, a different remedy (import once), hence a distinct code. Same bucket
    # and source as its sibling, NOT GDScript-mirrored.
    ErrorCodeSpec(
        "live_main_scene_unresolved",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "The conservative file precheck determined that the main scene is a"
        " `uid://` with no `uid_cache.bin` under the configured project data"
        " directory and no `--scene` selector was given; refused before daemon or"
        " Engine session launch to avoid Godot's native alert on macOS, even headless.",
    ),
    # Per live-operation failures the gda harness reports for `perf` (#223). Same
    # shape as the #220 game op-errors above: LIVE-category, classifier-source,
    # exit_code EXIT_LIVE, harness-mirrored (a test mirrors them against the harness
    # LIVE_ERROR_* consts). A stalled/crashed engine is caught by the daemon-level
    # `live_timeout`, not a perf-specific code: the time-windowed base finalizes on
    # sample count (reached before any frame ceiling), so it never emits its own
    # timeout — there is no `live_perf_timeout`.
    ErrorCodeSpec(
        "live_perf_node_not_found",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live perf monitor's node path does not resolve to a node in the running scene tree.",
    ),
    ErrorCodeSpec(
        "live_perf_property_not_found",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live perf monitor targeted a property the running node does not expose for reading.",
    ),
    ErrorCodeSpec(
        "live_perf_signal_not_found",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live perf monitor targeted a signal the running node does not declare.",
    ),
    # Per live-operation failures the gda harness reports for `input` (#221). Same
    # shape as the #220/#223 op-errors above: LIVE-category, classifier-source,
    # exit_code EXIT_LIVE, harness-mirrored (a test mirrors them against the harness
    # LIVE_ERROR_* consts). Only the failures the harness genuinely needs the LIVE
    # engine to decide are minted (the #239 lesson): a key name the engine cannot
    # resolve to a keycode (live_invalid_key), an action absent from the running
    # InputMap (live_unknown_action), and a sequence event whose type the harness
    # does not recognize (live_invalid_event_spec — the defensive arm for a request
    # that reached the harness without passing the model). Every other malformed
    # input is rejected model-side (ADR-0015) and never reaches the harness.
    ErrorCodeSpec(
        "live_invalid_key",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live input key event named a key the engine could not resolve to a keycode.",
    ),
    ErrorCodeSpec(
        "live_unknown_action",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live input action targeted an action the running game's InputMap does not declare.",
    ),
    ErrorCodeSpec(
        "live_invalid_event_spec",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live input sequence event has a type the harness does not recognize.",
    ),
    # The predicate-capture failure the gda harness reports for #661: a
    # `screen capture --await-*` predicate that never held within its declared
    # frame bound. LIVE-category, classifier-source, harness-mirrored like the
    # other per-op codes; the message carries the last observed value so the
    # agent can see how far the state got.
    ErrorCodeSpec(
        "live_predicate_unmet",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live `screen capture` predicate (`--await-*`) did not hold within its "
        "declared frame bound.",
    ),
    # The `screen` capture failure the gda harness reports for #222. Same shape as
    # the other per-op LIVE codes (LIVE-category, classifier-source, exit_code
    # EXIT_LIVE, harness-mirrored): a viewport capture needs a real DisplayServer,
    # which the dummy headless one is not — so a screen op on a session NOT started
    # `gda daemon start --windowed` reports this, the self-revealing remediation
    # (start the daemon windowed). The harness guards on
    # `DisplayServer.get_name() == "headless"` before touching the viewport.
    ErrorCodeSpec(
        "live_display_unavailable",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live screen capture ran on a headless engine session (the dummy "
        "DisplayServer cannot read pixels); start the daemon windowed with "
        "`gda daemon start --windowed`.",
    ),
    # A pre-launch platform precondition, not a live-runtime failure: live needs
    # Unix domain sockets, which are UNIX-only, so it is an ENVIRONMENT-category
    # code in the binary_not_found bucket (ADR-0021), decided before any engine
    # launch and classifier-source (no operation reports it).
    ErrorCodeSpec(
        "live_unsupported_platform",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.CLASSIFIER,
        "Live operations require a UNIX platform (macOS/Linux); they use Unix"
        " domain sockets, which are unavailable here. Phase-1 headless is"
        " unaffected.",
    ),
    # A pre-launch DISPLAY precondition, not a live-runtime failure: a windowed
    # engine session needs a usable host DisplayServer, and a host with none makes a
    # windowed Godot abort during DisplayServer registration. So `gda daemon start
    # --windowed` refuses BEFORE spawning — an ENVIRONMENT-category code in the
    # binary_not_found (exit 127) bucket, mirroring `live_unsupported_platform`,
    # decided pre-launch and classifier-source (no operation reports it), NOT
    # GDScript-mirrored (#345).
    ErrorCodeSpec(
        "live_windowed_unavailable",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.CLASSIFIER,
        "A windowed Engine session was requested (`gda daemon start --windowed`) but"
        " the host has no usable DisplayServer (no on-console GUI session / no"
        " $DISPLAY), so the session cannot come up; refused before spawning Godot.",
    ),
    # The PERMISSION half of the pre-launch display precondition (#667). Same
    # category/exit as `live_windowed_unavailable` — both refuse a windowed start
    # pre-launch — but a different FACT about the world, and so a different code: the
    # window-server lookup was REFUSED, so gda never got to observe whether a session
    # exists. Conflating them is what the dogfooding (GDA-DF-029) hit — a sandboxed
    # run read as a machine-capability gap, so rendered QA was silently skipped
    # instead of retried outside the sandbox. The code deliberately does not claim
    # the host HAS a window server: seatbelt refuses an unregistered name under a
    # blanket-deny profile too, so the refusal proves confinement, not existence
    # (#667 review). Distinct from `live_display_unavailable`, the harness's
    # CAPTURE-time code for a session started headless. Classifier-source, NOT
    # GDScript-mirrored.
    ErrorCodeSpec(
        "live_windowed_permission_denied",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.CLASSIFIER,
        "A windowed Engine session was requested (`gda daemon start --windowed`) but"
        " this process is denied the window-server lookup (e.g. a sandbox), so gda"
        " cannot tell whether the host has one; re-run outside the restriction to"
        " find out rather than recording the host as display-less.",
    ),
    # The FILESYSTEM half of the GDA-DF-029 dogfooding find (#700), alongside the
    # DISPLAY half above: `install_harness` reads and writes under `res://addons`
    # and reads then rewrites `project.godot` BEFORE any engine exists (ADR-0018),
    # and `HarnessSnapshot.capture` reads the same paths a step earlier still — so a
    # filesystem-restricted sandbox used to surface as a raw `PermissionError`
    # traceback from any of those points, the same "environment refusal read as a
    # crash" failure mode #667 fixed for the display probe. Classifier-source: `gda`
    # itself classifies the OSError one of those calls raises, no operation reports
    # it.
    #
    # Named `_permission_denied`, not `_unwritable` (#700 recheck): the first cut of
    # this code covered only a WRITE denial and named itself accordingly, then a
    # follow-up review found `_read_config` sits inside the SAME guarded call as the
    # two writes — so that wording silently mislabeled a genuine READ failure as a
    # write refusal. One code still covers every access `install_harness` /
    # `HarnessSnapshot.capture` can have been REFUSED (a `mkdir`/write under
    # `res://addons` in `_materialize`, the `project.godot` read that decides whether
    # the autoload needs touching, the `project.godot` write, or the pre-install
    # snapshot read) — they are all the same fact, an OS-refused access — but the
    # CODE NAME no longer asserts which direction, and the message stays equally
    # neutral wherever the call site cannot tell read from write apart on its own
    # (`gda.commands.daemon` docstrings). Both `install_harness` writes trigger the
    # same `HarnessSnapshot` rollback (#654); a capture-site read failure needs none
    # — nothing has been written yet. NOT GDScript-mirrored: nothing here runs inside
    # the engine.
    #
    # SCOPED TO A REFUSAL (#700 review round 2). The classifier keys on `errno`
    # (`gda.commands.daemon._is_filesystem_refusal`: EACCES / EPERM / EROFS), not on
    # the `OSError` class — which also covers a full disk, a missing path, a
    # not-a-directory and an I/O error, none of which this sentence describes. A code
    # is public ABI with a pinned meaning (this ADR-0002 registry), so handing it to
    # those would teach an agent to escape a sandbox for a storage or path defect.
    # They keep their pre-#700 behaviour instead — the same `HarnessSnapshot`
    # rollback then propagate where a snapshot exists, and direct propagation when the
    # capture read itself failed, which wrote nothing to roll back — which is why #700
    # registers ONE code and not a second, generic filesystem one nothing has yet
    # asked for.
    ErrorCodeSpec(
        "harness_install_permission_denied",
        ErrorCategory.ENVIRONMENT,
        EXIT_NOT_FOUND,
        ErrorCodeSource.CLASSIFIER,
        "The gda harness install (`gda daemon start` — including a repeat start's"
        " self-sync — or `gda daemon install`) was REFUSED access to the project's"
        " filesystem: the OS denied the permission, or the filesystem is read-only."
        " The message names the path that was refused, and any partial write is"
        " rolled back where the filesystem still allows it. A filesystem failure that"
        " is NOT a refusal — a full disk, a missing or malformed path, an I/O"
        " error — does not carry this code; it propagates as before: after the same"
        " rollback when a snapshot exists, and directly when the failure came from"
        " the pre-install snapshot read itself, which has written nothing to roll"
        " back.",
    ),
)

ERROR_CODE_BY_CODE: dict[str, ErrorCodeSpec] = {spec.code: spec for spec in ERROR_CODES}

OPERATION_ERROR_CODES: frozenset[str] = frozenset(
    spec.code for spec in ERROR_CODES if spec.source is ErrorCodeSource.OPERATION
)

# The Phase-2 live failure codes (ADR-0017, ADR-0021). Surfaced from a sentinel
# error envelope by the daemon IPC client / the daemon and mapped to the
# registered code by ``classify_live`` — the live analogue of OPERATION_ERROR_CODES.
LIVE_ERROR_CODES: frozenset[str] = frozenset(
    spec.code for spec in ERROR_CODES if spec.category is ErrorCategory.LIVE
)
