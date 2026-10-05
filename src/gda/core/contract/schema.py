"""The command-surface schema models (ADR-0004).

Split out of the shared contract core by ADR-0045 §2: how one command describes
itself — its argv bindings and its ``--schema`` document — and how the whole
surface is listed in the manifest.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gda.core.contract.envelope import GdaErrorEnvelope, LiveStackConstraints
from gda.core.engine.execution import ExecutionKind


class ArgvKind(str, Enum):
    """How one operation parameter is supplied on a ``gda`` command line (#669).

    ``argument`` is positional — its place in the command line is its identity;
    ``option`` is named — its ``--spelling`` is. Typed as an enum so the emitted
    schema constrains the value rather than leaving it free text.
    """

    ARGUMENT = "argument"
    OPTION = "option"


# The two spellings a binding can be, as a JSON-Schema rule so a consumer can
# CHECK the pairing rather than discover it (#669 review). It mirrors
# :meth:`ArgvBinding._check_spelling`, which stays the enforcing authority — a
# corpus test runs one set of combinations through both this published rule and
# the model and requires the same verdict, so the two cannot drift. Published
# because the alternative reading is worse than useless: a consumer that sees
# `position: null` on an option and `option: null` on a positional has to guess
# which key is authoritative, and a binding claiming both (or neither) would look
# writable.
_ARGV_BINDING_SPELLING_SCHEMA: dict[str, Any] = {
    "oneOf": [
        # A positional: it has a place, no spelling, and cannot be a bare flag.
        {
            "properties": {
                "kind": {"const": "argument"},
                "option": {"type": "null"},
                "position": {"type": "integer"},
                "flag": {"const": False},
            },
        },
        # An option: it has a spelling and no place.
        {
            "properties": {
                "kind": {"const": "option"},
                "option": {"type": "string"},
                "position": {"type": "null"},
            },
        },
    ]
}


# The derivation is gda.headless.command_argv_bindings.
class ArgvBinding(BaseModel):
    """How ONE operation parameter is spelled on the command line (#669).

    The missing half of a command's self-description: ``input`` says WHAT a
    command needs, this says HOW to write it as argv. Derived from the live
    Typer/Click parameter at emission time; the rationale, the boundaries and
    the case inventory are the ADR-0004 amendment (#669).

    Reading it: ``kind`` picks the spelling rule — a positional goes at
    ``position`` (0-based, among positionals only), a named one is written as
    ``option``. ``flag`` marks an option that takes NO value (write it bare),
    ``multiple`` one that is repeated per value (a repeatable option, or a
    variadic positional), and ``json_value`` one whose single token is the
    property's JSON encoding rather than a plain scalar. ``required`` is the
    DECLARED requirement, unaffected by the relaxed parse ``--schema`` itself uses
    (issue #36).
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_ARGV_BINDING_SPELLING_SCHEMA
    )

    # Descriptions stay terse: the manifest repeats them per parameter of every
    # command, so prose here is paid hundreds of times (the #667 measurement).
    name: str = Field(
        description=(
            "The parameter's internal name; write it as `option`, or at `position`."
        )
    )
    input_property: str | None = Field(
        description=(
            "The `input` schema property this parameter fills; null only where the "
            "binding cannot be resolved to one."
        )
    )
    kind: ArgvKind = Field(description="Positional (argument) or named (option).")
    option: str | None = Field(
        description="The option spelling, e.g. --output; null for a positional."
    )
    position: int | None = Field(
        description="0-based position among the positionals; null for an option."
    )
    required: bool = Field(description="Whether the command line must supply it.")
    flag: bool = Field(description="A valueless option: write it bare.")
    multiple: bool = Field(description="Repeat it once per value.")
    json_value: bool = Field(
        description="Write the whole value as one JSON-encoded token."
    )

    @model_validator(mode="after")
    def _check_spelling(self) -> "ArgvBinding":
        """Reject a binding no caller could write (#669 review).

        The type system allows a positional carrying an option spelling, an
        option carrying a position, or a binding with neither — states the
        derivation cannot produce but the model could hold, and a consumer
        reading one would have no way to tell which key to believe. Enforced
        here, published as ``_ARGV_BINDING_SPELLING_SCHEMA``.
        """
        if self.kind is ArgvKind.ARGUMENT:
            if self.option is not None:
                raise ValueError("a positional binding carries no option spelling.")
            if self.position is None:
                raise ValueError("a positional binding needs its position.")
            if self.flag:
                raise ValueError("a positional binding is never a valueless flag.")
        else:
            if self.option is None:
                raise ValueError("an option binding needs its option spelling.")
            if self.position is not None:
                raise ValueError("an option binding occupies no position.")
        return self


class CommandSchema(BaseModel):
    """A command's self-description: its ``input``, ``output`` and ``error`` JSON Schemas (ADR-0004).

    ``--schema`` emits this. ``input`` and ``output`` are derived from the
    command's own typed models via :meth:`of`, so the contract is never
    hand-maintained: ``input`` from the params model, ``output`` from the same
    *success* result model that backs ``--json``. ``error`` is the **uniform**
    failure-envelope schema, identical for every command, produced from the one
    shared :class:`GdaErrorEnvelope` model — zero per-command maintenance (#43).

    ``gda-mcp`` later maps ``input`` → ``input_schema`` and ``output`` →
    ``output_schema`` (success / ``structured_content``) mechanically. The
    ``error`` half is kept OUT of ``output``: a non-zero-exit failure maps to
    MCP's separate ``is_error`` channel, so the adapter must not fold ``error``
    into ``output_schema``.

    ``kind`` carries the command's static execution channel as the typed
    :class:`~gda.core.engine.execution.ExecutionKind` (serialized as the lowercase value
    ``"headless"`` / ``"export"`` / ``"live"``), taken from the command
    descriptor's single source of truth (``HeadlessCommand.kind``), so an agent
    can branch on a command's channel without inferring it (issue #230, stories
    14/15/24). Typing it as the enum makes the value enum-constrained in any
    derived schema. It is additive: gda-mcp maps only ``input`` / ``output`` /
    ``description`` and ignores it, so adding it is backward-compatible
    (ADR-0012). It is ``None`` only when a self-description is emitted without a
    backing command (e.g. ``gda schema``); a real per-command ``--schema`` always
    carries a kind.

    ``constraints`` carries the command's :class:`LiveStackConstraints` — the
    platform / Godot-version precondition for gda's daemon/live stack — or
    ``None`` for a command with no live-stack dependence (issue #233). Both forms
    are sourced from the single :func:`gda.core.engine.execution.live_stack_constraints`
    authority. Additive and ignored by gda-mcp (ADR-0012, ADR-0004).

    ``argv`` carries the command's :class:`ArgvBinding` list — how each of the
    parameters ``input`` describes is spelled on a command line (issue #669),
    derived from the live Typer/Click parameters. It is a SIBLING of the schema
    halves, never a key inside them, so gda-mcp's ``input_schema`` /
    ``output_schema`` are byte-identical with or without it (ADR-0012); an empty
    list for a command with no operation parameters.
    """

    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]
    kind: ExecutionKind | None = None
    constraints: LiveStackConstraints | None = None
    argv: list[ArgvBinding] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        kind: ExecutionKind | None = None,
        constraints: LiveStackConstraints | None = None,
        argv: "list[ArgvBinding] | None" = None,
    ) -> "CommandSchema":
        """Derive the contract from a command's params and result models.

        ``error`` is the shared failure-envelope schema, the same for every
        command, so it takes no per-command model argument. ``kind`` is the
        command's static :class:`~gda.core.engine.execution.ExecutionKind` (issue #230); it
        serializes to its lowercase string because ``ExecutionKind`` subclasses
        ``str``. ``constraints`` is the command's live-stack precondition or
        ``None`` (issue #233), computed by the caller from the single
        :func:`gda.core.engine.execution.live_stack_constraints` authority. ``argv`` is the
        command's CLI-spelling projection (issue #669), computed by the caller
        from the single :func:`gda.headless.command_argv_bindings` derivation off
        the live Click parameters.
        """
        return cls(
            input=input_model.model_json_schema(),
            output=output_model.model_json_schema(),
            error=GdaErrorEnvelope.model_json_schema(),
            kind=kind,
            constraints=constraints,
            argv=argv or [],
        )


# ``kind`` is gda.core.engine.execution.ExecutionKind; ``constraints`` comes from the same
# gda.core.engine.execution.live_stack_constraints authority as the per-command schema.
class CommandManifestEntry(BaseModel):
    """One command's entry in the aggregate surface manifest (ADR-0012).

    The whole-surface generalisation of a single command's ``CommandSchema``:
    it carries the same model-derived ``input`` / ``output`` / ``error`` halves,
    plus the two facts gda-mcp needs to register a tool — ``name`` (the
    ``<group> <command>`` MCP mapping basis, ADR-0005, e.g. ``scene create``;
    bare for a meta command such as ``info``) and the command's ``description``
    (its help text, which flows into the MCP tool description).

    ``kind`` mirrors ``CommandSchema``'s: the entry's static execution
    channel as the typed ``ExecutionKind`` (serialized
    ``"headless"`` / ``"export"`` / ``"live"``), taken from the same descriptor
    source of truth so the aggregate and per-command forms agree (issue #230).
    Additive and ignored by gda-mcp (ADR-0012). Unlike ``CommandSchema``'s
    optional ``kind``, here it is **required**: every aggregate entry is a
    dispatchable command with a backing descriptor, so the self-described surface
    schema (``gda schema --schema``) guarantees the field and constrains it to
    the execution-kind enum — a consumer can rely on it always being present.

    ``constraints`` mirrors ``CommandSchema``'s: the entry's
    ``LiveStackConstraints``, or ``None`` for a command with no live-stack
    dependence (issue #233), from the same single authority so the aggregate and
    per-command forms agree. Unlike ``CommandSchema``'s defaulted field, the
    **key is required** here (every dispatchable entry is computed from a backing
    descriptor, so the self-described surface schema guarantees the key is
    present) while its **value is nullable** (``null`` for non-live-stack
    commands) — a consumer can rely on the key always being there to read.

    ``argv`` mirrors ``CommandSchema``'s: how each of the command's
    parameters is spelled on a command line (issue #669), from the same live
    Click parameters, so the aggregate and per-command forms agree. **Required**
    here for the same reason ``kind`` is — every entry is a real command whose
    signature can be walked — with an empty list where a command takes no
    operation parameters. Additive and ignored by gda-mcp (ADR-0012).
    """

    name: str
    description: str
    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]
    kind: ExecutionKind
    constraints: LiveStackConstraints | None
    argv: list[ArgvBinding]


class SurfaceManifest(BaseModel):
    """The whole ``gda`` command surface as one document (ADR-0012).

    What ``gda schema`` emits and gda-mcp introspects once at startup: one
    ``CommandManifestEntry`` per command in every group. An object (rather
    than a bare array) leaves room for top-level metadata later and gives the
    manifest its own schema, so ``gda schema --schema`` self-describes.
    """

    commands: list[CommandManifestEntry]
