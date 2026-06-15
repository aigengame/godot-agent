"""Authoritative registry of public ``GdaError.code`` values.

The registry is the machine-readable companion to ADR-0002's table. Every code
emitted in a public ``GdaError`` must be declared here; GDScript mirrors only
the ``operation`` source subset because only those codes are reported by
headless operations.
"""

from dataclasses import dataclass
from enum import Enum

from gda.exit_codes import (
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
        "The operation dispatcher was invoked without the required operation name.",
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
        "The operation dispatcher received params that are not a JSON object.",
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
        "project_not_found",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "An operation that enumerates a project's res:// tree ran without a resolved Godot project.",
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
        "missing_dependency",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A scene's declared nodes vanished or degraded on load — an"
        " unresolvable instanced sub-scene or an unavailable node class;"
        " re-saving would silently drop or downgrade them.",
    ),
    ErrorCodeSpec(
        "uninstantiable_script",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A registered class_name's script can no longer be loaded, compiled,"
        " or constructed, so it cannot be instantiated as a node.",
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
        "A node move targeted the node itself or one of its own descendants,"
        " which would detach the moved subtree from the scene.",
    ),
    ErrorCodeSpec(
        "unknown_property",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested property does not exist as a settable property on the node.",
    ),
    ErrorCodeSpec(
        "uncoercible_value",
        ErrorCategory.OPERATION,
        EXIT_OPERATION,
        ErrorCodeSource.OPERATION,
        "A supplied value cannot be coerced to the property's declared Godot type.",
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
        "contract_violation",
        ErrorCategory.PARSE,
        EXIT_PARSE,
        ErrorCodeSource.PARSER,
        "The process claimed success but violated the structured-output contract.",
    ),
)

ERROR_CODE_BY_CODE: dict[str, ErrorCodeSpec] = {spec.code: spec for spec in ERROR_CODES}

OPERATION_ERROR_CODES: frozenset[str] = frozenset(
    spec.code for spec in ERROR_CODES if spec.source is ErrorCodeSource.OPERATION
)
