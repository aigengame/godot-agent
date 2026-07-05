"""Authoritative registry of public ``GdaError.code`` values.

The registry is the machine-readable companion to ADR-0002's table. Every code
emitted in a public ``GdaError`` must be declared here; GDScript mirrors only
the ``operation`` source subset because only those codes are reported by
headless operations.
"""

from dataclasses import dataclass
from enum import Enum

from gda.exit_codes import (
    EXIT_LIVE,
    EXIT_NOT_FOUND,
    EXIT_OPERATION,
    EXIT_PARSE,
    EXIT_TIMEOUT,
    EXIT_VERSION,
)
from gda.models import ErrorCategory


class ErrorCodeSource(str, Enum):
    """Where a public ``GdaError.code`` originates."""

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
    exits 124), the ``source`` that may report it, and its ``description``.
    Failure construction derives ``category`` and ``exit_code`` from here, so it
    no longer restates either at the call site — both come from the row
    (ADR-0002, #141).
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
        "Godot launched but did not return before the runner timeout.",
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
        "gda ran without a usable resolved Godot project: an operation needed one and none was resolved, or an explicit --project was empty, or a --project/$GDA_PROJECT does not name a Godot project (no project.godot).",
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
        "A script could not be attached to a node because it does not compile.",
    ),
    ErrorCodeSpec(
        "incompatible_script_type",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A script compiles but its native base type is incompatible with the target node's type.",
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
        "An export run targeted a preset that has no configured export_path.",
    ),
    ErrorCodeSpec(
        "export_templates_missing",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "An export run needs the export templates for the running engine version, which are not installed.",
    ),
    ErrorCodeSpec(
        "export_output_parent_failed",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "An export run could not create the output parent directory before native export.",
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
        " limit; the payload is contract-conformant, the limit is wrapper-side.",
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
        "The engine session disconnected before the live operation returned"
        " (the game crashed or the harness connection dropped).",
    ),
    ErrorCodeSpec(
        "live_timeout",
        ErrorCategory.LIVE,
        EXIT_LIVE,
        ErrorCodeSource.CLASSIFIER,
        "A live operation did not return from the engine session before the"
        " daemon's timeout.",
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
        "DisplayServer cannot read pixels); start the daemon with `gda daemon start "
        "--windowed`.",
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
        " domain sockets, which are unavailable here.",
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
        "A windowed live session was requested (`gda daemon start --windowed`) but"
        " the host has no usable DisplayServer (no on-console GUI session / no"
        " $DISPLAY), so the session cannot come up; refused before spawning Godot.",
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
