"""Authoritative registry of public ``GdaError.code`` values.

The registry is the machine-readable companion to ADR-0002's table. Every code
emitted in a public ``GdaError`` must be declared here; GDScript mirrors only
the ``operation`` source subset because only those codes are reported by
headless operations.
"""

from dataclasses import dataclass
from enum import Enum

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
    """One public ``GdaError.code`` registry entry."""

    code: str
    category: ErrorCategory
    source: ErrorCodeSource
    description: str


ERROR_CODES: tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        "binary_not_found",
        ErrorCategory.ENVIRONMENT,
        ErrorCodeSource.RUNNER,
        "The Godot binary could not be launched.",
    ),
    ErrorCodeSpec(
        "launch_timeout",
        ErrorCategory.ENVIRONMENT,
        ErrorCodeSource.RUNNER,
        "Godot launched but did not return before the runner timeout.",
    ),
    ErrorCodeSpec(
        "unsupported_version",
        ErrorCategory.VERSION,
        ErrorCodeSource.VERSION_GATE,
        "The detected Godot version is below the supported minimum.",
    ),
    ErrorCodeSpec(
        "engine_crashed",
        ErrorCategory.OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "Godot terminated abnormally, such as by signal death.",
    ),
    ErrorCodeSpec(
        "operation_failed",
        ErrorCategory.OPERATION,
        ErrorCodeSource.CLASSIFIER,
        "The engine or operation failed without a valid registered operation error envelope.",
    ),
    ErrorCodeSpec(
        "usage_error",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "The operation dispatcher was invoked without the required operation name.",
    ),
    ErrorCodeSpec(
        "unknown_operation",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "The operation dispatcher received an unknown operation name.",
    ),
    ErrorCodeSpec(
        "invalid_params",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "The operation dispatcher received params that are not a JSON object.",
    ),
    ErrorCodeSpec(
        "invalid_path",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A required path parameter is missing or invalid.",
    ),
    ErrorCodeSpec(
        "invalid_root_type",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested Godot root node type cannot be instantiated as a Node.",
    ),
    ErrorCodeSpec(
        "invalid_root_name",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested root node name is empty or would be rewritten by Godot.",
    ),
    ErrorCodeSpec(
        "already_exists",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A create operation target already exists and will not be overwritten.",
    ),
    ErrorCodeSpec(
        "save_failed",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A scene could not be packed or saved.",
    ),
    ErrorCodeSpec(
        "delete_failed",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A file could not be removed from disk.",
    ),
    ErrorCodeSpec(
        "project_not_found",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "An operation that enumerates a project's res:// tree ran without a resolved Godot project.",
    ),
    ErrorCodeSpec(
        "path_not_found",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested file does not exist.",
    ),
    ErrorCodeSpec(
        "not_a_scene",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested file cannot be loaded as a PackedScene.",
    ),
    ErrorCodeSpec(
        "parent_not_found",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested parent node path does not resolve to a node in the scene.",
    ),
    ErrorCodeSpec(
        "invalid_node_type",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node type is neither an instantiable Node class nor a registered class_name.",
    ),
    ErrorCodeSpec(
        "invalid_node_name",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node name is empty or would be rewritten by Godot.",
    ),
    ErrorCodeSpec(
        "duplicate_node_name",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "The parent node already has a child with the requested name.",
    ),
    ErrorCodeSpec(
        "missing_dependency",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A scene's declared nodes vanished or degraded on load — an"
        " unresolvable instanced sub-scene or an unavailable node class;"
        " re-saving would silently drop or downgrade them.",
    ),
    ErrorCodeSpec(
        "uninstantiable_script",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A registered class_name's script can no longer be loaded, compiled,"
        " or constructed, so it cannot be instantiated as a node.",
    ),
    ErrorCodeSpec(
        "node_not_found",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested node path does not resolve to a node in the scene.",
    ),
    ErrorCodeSpec(
        "unknown_property",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A requested property does not exist as a settable property on the node.",
    ),
    ErrorCodeSpec(
        "uncoercible_value",
        ErrorCategory.OPERATION,
        ErrorCodeSource.OPERATION,
        "A supplied value cannot be coerced to the property's declared Godot type.",
    ),
    ErrorCodeSpec(
        "contract_violation",
        ErrorCategory.PARSE,
        ErrorCodeSource.PARSER,
        "The process claimed success but violated the structured-output contract.",
    ),
)

ERROR_CODE_BY_CODE: dict[str, ErrorCodeSpec] = {spec.code: spec for spec in ERROR_CODES}

OPERATION_ERROR_CODES: frozenset[str] = frozenset(
    spec.code for spec in ERROR_CODES if spec.source is ErrorCodeSource.OPERATION
)
