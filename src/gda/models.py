"""Typed result models (ADR-0004).

Each command's result is carried by a Pydantic model rather than an ad-hoc
dict, so the same model both serializes the ``--json`` output now and produces
the ``--schema`` document later (``model_json_schema()``) without
hand-maintaining the contract twice.
"""

from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from gda.execution import ExecutionKind
from gda.live_numbers import find_unrepresentable
from gda.project import is_engine_virtual_path
from gda.script_errors import ScriptError


class ErrorCategory(str, Enum):
    """The coarse buckets a ``gda`` operation can fail into (issue #3).

    This is the coarse axis; each category fans out to one or more finer,
    stable ``GdaError.code`` values (e.g. ENVIRONMENT → ``binary_not_found`` /
    ``launch_timeout``; OPERATION → ``operation_failed`` / ``engine_crashed``).
    See ``gda.errors.classify_run`` for the category→code decision tree.

    ENVIRONMENT covers everything before the operation produces a result — the
    binary not launching, or launching and hanging past the timeout. VERSION is
    a launched engine below the supported minimum (ADR-0003). OPERATION is a
    launched engine that failed to deliver a result (the operation reported an
    error, or the engine crashed). PARSE is a violation of the structured-output
    contract (ADR-0002): a missing/malformed sentinel or a wrong-shape payload.
    LIVE is a Phase-2 live operation failing against ``gda-daemon`` / the engine
    session — no running daemon, a lost session, or a live timeout (ADR-0017,
    ADR-0021). USAGE is the one bucket that precedes all of them: gda could not
    resolve WHAT was asked for — an unrecognized command or option — so no
    operation was ever identified, let alone run (#670).
    """

    ENVIRONMENT = "environment"
    VERSION = "version"
    OPERATION = "operation"
    PARSE = "parse"
    LIVE = "live"
    USAGE = "usage"


# WHY this exists (kept as a comment, not a docstring): a model docstring becomes
# the schema `description`, and the error envelope's schema is repeated for EVERY
# command in `gda schema` — so rationale here would be paid ~67 times by every agent
# reading the manifest. The decision and its reasoning live in the ADR-0004
# amendment (#667); the docstring below stays the one-line contract.
#
# The short version: gda decides some ENVIRONMENT failures by asking the host a
# question directly ("can a window open here?") rather than by observing an engine
# run. WHICH OS call answered separates "this machine cannot do it" from "this
# PROCESS was not allowed to" — skip the capability, versus retry outside the
# restriction. #667: automation read a sandbox denial as a machine-capability gap
# and silently skipped rendered QA, because that fact lived only in prose.
class EnvironmentProbe(BaseModel):
    """The host call that decided an environment failure: its ``name`` and ``platform``."""

    model_config = ConfigDict(extra="forbid")

    # Descriptions are deliberately terse: each one is repeated per command in the
    # manifest, so prose here is paid ~67 times over (#667 review measured the cost).
    name: str = Field(
        description="The OS call that decided this failure, e.g. CGSessionCopyCurrentDictionary."
    )
    platform: str = Field(
        description="The sys.platform the probe ran on, e.g. darwin or linux."
    )


# WHY this enum lives here and not beside ``script run`` (#687): it is projected
# into the SHARED failure envelope through ``FailureEvidence.termination_phase``, so
# it is now a property of the public contract rather than of one command. Prose is a
# comment for the same reason the two models around it keep theirs out of the schema.
#
# The set answers the question an agent asks of a run that did not finish: was it
# working, or was it stuck? An earlier draft named a third phase for "killed at the
# timeout", which both timeout phases already are — what a reader cannot infer from
# the code is whether the run had got anywhere, so that is what these distinguish.
class TerminationPhase(str, Enum):
    """How far a run gda ENDED had got when gda ended it (#655)."""

    #: gda ended the run at its timeout and the engine had written NOTHING to
    #: either stream. Rare and deliberately narrow: Godot prints its version banner
    #: within ~0.1s of a normal spawn (measured), so this marks the engine never
    #: reaching its own startup output — a wrapper that did not exec, or a hang
    #: before stdio.
    LAUNCHED = "launched"
    #: gda ended the run at its timeout after output had appeared. The usual timeout
    #: phase: the run was alive and did not finish, so the captured tail is how far
    #: it got and the timeout is the knob.
    OUTPUT_SEEN = "output_seen"
    #: gda ended the run EARLY, before its timeout: a script error appeared, the
    #: declared completion marker did not, and the run went silent (``script run``
    #: only — it is the one channel with a Completion marker contract).
    ABORTED_ON_ERROR = "aborted_on_error"


# WHY this shape (kept as a comment, not a docstring — the schema cost rule the
# models around it follow): #687 decided that the uniform failure ABI carries
# optional TYPED evidence, and decided it as ONE universal fixed shape rather than a
# per-command ``error`` schema, because ADR-0004 fixes the ``error`` half as "the one
# shared GdaErrorEnvelope schema, identical for every command". The per-operation
# variability lives INSIDE this object — every field is individually optional and
# omitted when absent — so a timeout populates the clocks and a strict script failure
# populates the status, without either being a different envelope.
#
# What may enter it: the fact must ALREADY be computed on the failure path, be
# unrecoverable from the envelope without parsing prose, and change what the caller
# does next. That is why the ``script run`` abort's silence window and declared
# marker are NOT here — both are the caller's own inputs — while the parsed script
# errors are: they existed and were thrown away (#651). ADR-0004's #687 amendment is
# the AUTHORITY for that criterion and for the producer set it currently admits;
# this restatement is the reader's copy beside the code, not a second rule.
#
# What it is NOT: a substitute for branching on ``code``. The verdict stays the code;
# this is the evidence behind it. In particular a recognized error in
# ``script_errors`` under a ``launch_timeout`` is ADVISORY and does not re-verdict the
# timeout — the decision recorded in ADR-0002 for #716.
class FailureEvidence(BaseModel):
    """Typed evidence about a failure; a field this run cannot compute is omitted."""

    model_config = ConfigDict(extra="forbid")

    exit_status: int | None = Field(
        default=None,
        description=(
            "The child process's own exit status, on a failure whose verdict IS "
            "that status (script run --strict). Not the gda process exit code."
        ),
    )
    elapsed_seconds: float | None = Field(
        default=None,
        description="Wall clock the run had used when gda ended it.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        description=(
            "The timeout ceiling this run reached. Set only on a timeout verdict, "
            "naming the bound to raise before a rerun; a run gda ended short of "
            "its ceiling (script_aborted) omits it — that --timeout is the "
            "caller's own input."
        ),
    )
    termination_phase: TerminationPhase | None = Field(
        default=None,
        description="How far the run gda ended had got.",
    )
    script_errors: list[ScriptError] | None = Field(
        default=None,
        description=(
            "Engine/script errors recognized in this run's stderr, in emission "
            "order — the same records, with the same keys, a successful run "
            "reports as 'diagnostics'. THREE states, not two: absent means this "
            "failure's channel does not parse stderr at all, so read "
            "'diagnostics'; [] means it parsed and recognized none, which is "
            "itself a finding; a non-empty list is what it recognized. Advisory: "
            "the verdict is 'code', never an entry here."
        ),
    )
    # The three coordinates of a `target_outside_project` refusal (#697/#763):
    # where the target is, which project gda used, and which one owns it. Each is
    # omitted when this particular refusal does not know it — `owning_project`
    # whenever nothing above the target claims it, and both of the others on the
    # one refusal decided before a project is resolved (`script run`'s pre-launch
    # address gate). They are reported rather than acted on, which is the whole
    # shape of ADR-0006's 2026-08-31 amendment: gda names the owner it found and
    # refuses, instead of adopting it as the call's root.
    target_location: str | None = Field(
        default=None,
        description=(
            "Where the refused target really is, resolved — the coordinate for "
            "finding which project owns it."
        ),
    )
    project_root: str | None = Field(
        default=None,
        description=(
            "The project gda resolved for this call, in its resolved form — the "
            "same value a successful result reports as 'project_root'. Omitted "
            "when no project resolved."
        ),
    )
    owning_project: str | None = Field(
        default=None,
        description=(
            "The Godot project that owns the refused target — the one to pass as "
            "--project. Set only when gda found one above the target."
        ),
    )

    @field_serializer("script_errors")
    def _keep_the_published_script_error_shape(
        self, errors: list[ScriptError] | None
    ) -> list[dict[str, Any]] | None:
        """Serialize the records with their FULL key set, nulls included (#687 review).

        The failure envelope is emitted with ``exclude_none``
        (:func:`gda.headless.emit_failure`), which recurses. Without this, a null
        ``path`` / ``line`` would be dropped from the nested records and the SAME
        script error would carry different keys depending on which half of the
        contract a caller read it from — four keys on ``script run``'s success
        ``diagnostics``, two or three here — while both halves are described by one
        published ``ScriptError`` schema whose ``path`` / ``line`` say "or null".

        The omit-when-None rule the amendment rests on is about the OPTIONAL KEYS of
        the envelope (``probe`` / ``hint`` / ``evidence``) and this object's own
        fields, which is where it buys byte-identity for failures that compute no
        evidence. It was never a claim about the published shape of a model nested
        under one. So the rule stops at this boundary, and any future nested model
        that is also published on a success result gets the same treatment.
        """
        return (
            None
            if errors is None
            else [error.model_dump(mode="json") for error in errors]
        )


class GdaError(BaseModel):
    """A structured, stable failure of a ``gda`` operation (issue #3).

    Emitted as ``{"error": <this>}`` on stdout so an agent reacts to failure
    modes programmatically without parsing prose. ``category`` is the coarse,
    process-exit-code-aligned bucket; ``code`` is the finer, stable identifier;
    ``diagnostics`` carries the engine/script stderr surfaced per ADR-0002;
    ``probe`` is optional context on the few environment failures gda decides by
    probing the host (ADR-0004 amendment, #667); ``hint`` is the supported
    invocation to use instead, on the refusals gda recognizes as a near miss
    (#670); ``evidence`` is the typed evidence behind the verdict, on the failures
    that compute any (#687). All three optional keys are OMITTED when unset, never
    null, and so are ``evidence``'s own fields. The rule stops there: a model
    NESTED inside one of them keeps its full published key set, so a record reads
    the same on both halves of the contract (see
    :meth:`FailureEvidence._keep_the_published_script_error_shape`).
    """

    category: ErrorCategory
    code: str
    message: str
    diagnostics: str = ""
    # OMITTED — not ``null`` — from every failure that sets none: the emit path
    # (:func:`gda.headless.emit_failure`) serializes with ``exclude_none``, so each
    # other code's envelope JSON stays byte-identical to the pre-amendment contract.
    # Deliberately the minimal axis — WHICH host call decided — never the typed
    # EVIDENCE of a failure (parsed script errors, exit statuses), which #687 decided
    # separately and carries in ``evidence`` below (ADR-0004 amendments, #667/#687).
    probe: EnvironmentProbe | None = Field(
        default=None,
        description=(
            "Which host probe decided this environment failure; the key is omitted "
            "(never null) on failures that have none."
        ),
    )
    # Omitted, not null, the same way ``probe`` is — so every failure that offers no
    # correction keeps its pre-#670 envelope bytes. Deliberately the CORRECTED
    # INVOCATION and nothing else: it is the one thing the caller has to retype, and
    # keeping it a single command line means an agent re-issues it without composing
    # anything. Set only where gda RECOGNIZES the mistake (the curated near-miss
    # table, gda.hints) — never a difflib guess, which can name a different operation
    # than the one meant.
    hint: str | None = Field(
        default=None,
        description=(
            "The supported invocation to run instead; the key is omitted (never "
            "null) when gda has no correction to offer."
        ),
    )
    # The third optional key, on the axis ``probe`` and ``hint`` established (#687).
    # Same rule, same emit path: omitted rather than null, so every failure that
    # computes no evidence keeps its pre-#687 envelope bytes exactly.
    evidence: FailureEvidence | None = Field(
        default=None,
        description=(
            "Typed evidence behind this verdict (clocks, the child's exit status, "
            "recognized script errors); the key is omitted (never null) on failures "
            "that have none."
        ),
    )


class GdaErrorEnvelope(BaseModel):
    """The ``{"error": {...}}`` wrapper that discriminates a failure from a result.

    The success result (``EngineVersion``) is emitted bare, so the presence of
    the top-level ``error`` key is the stable success/failure discriminator.
    """

    error: GdaError


class OperationError(BaseModel):
    """The minimal operation-reported failure payload (ADR-0002).

    Headless operations only report the part they own: a registered operation
    error ``code`` and a human-readable ``message``. The Python classifier adds
    category and diagnostics when it builds the public ``GdaError``.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class OperationErrorEnvelope(BaseModel):
    """The sentinel payload shape for a headless operation failure."""

    model_config = ConfigDict(extra="forbid")

    error: OperationError


class LiveError(BaseModel):
    """A live-channel failure payload: the operation shape plus optional probe context.

    The daemon and the daemon IPC client report a live failure with the same ADR-0002
    envelope a headless operation uses, so this is :class:`OperationError` — with one
    addition. A windowed refusal at the daemon's authoritative launch boundary is
    decided by a HOST PROBE, and that context has to survive the relay, or the
    authoritative path would report a strictly poorer failure than the CLI's own
    fail-fast (#667). ``probe`` is therefore optional here and ABSENT from every other
    live envelope.

    The headless sentinel stays strict and probe-less: a GDScript operation has no host
    probe to report, so widening :class:`OperationError` would invite a key the other
    language can never fill. Two models, one per channel, is what keeps the
    cross-language contract narrow while the live channel carries what it actually knows.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    probe: EnvironmentProbe | None = None


class LiveErrorEnvelope(BaseModel):
    """The sentinel payload shape for a live-channel failure (``{"error": {...}}``)."""

    model_config = ConfigDict(extra="forbid")

    error: LiveError


class LiveStackConstraints(BaseModel):
    """The platform / Godot-version precondition a live-stack command needs (issue #233).

    A structured, machine-discoverable form of the constraint that ``gda``'s
    daemon/live stack carries — macOS/Linux only (Unix domain sockets) and, where
    a command launches/uses the engine, Godot 4.6+ (ADR-0021) — replacing the
    prose that used to live only in ``--help`` text and the manifest description.
    Present (non-``null``) only on commands that depend on the live stack: the
    LIVE-channel domain commands (``game …``) and the ``daemon`` lifecycle group;
    every other command's ``constraints`` is ``null``.

    Both facets come from the single :func:`gda.execution.live_stack_constraints`
    authority, so the structured field and the help/manifest prose cannot drift:

    - ``platforms`` is the uniform ``["linux", "macos"]`` (UDS) across the whole
      live-stack set.
    - ``min_godot_version`` is the dotted floor (``"4.6"``) only where a command
      launches/uses the engine (``game …``, ``daemon start``); ``None`` for
      ``daemon stop`` / ``daemon status``, which only talk to a running daemon
      over UDS and never touch the engine.

    Additive and ignored by gda-mcp, which maps only ``input`` / ``output`` /
    ``description`` (ADR-0012), so adding it is backward-compatible (ADR-0004).
    """

    platforms: list[str]
    # Required key, nullable value: the wrapper always supplies it (``None`` for
    # daemon stop/status), and the emitted objects always carry the key — so the
    # self-described schema marks it required, matching the actual ABI (issue #233,
    # PR #245 review). Not defaulted, or the schema would allow the key's omission.
    min_godot_version: str | None


class ArgvKind(str, Enum):
    """How one operation parameter is supplied on a ``gda`` command line (#669).

    ``ARGUMENT`` is positional — its place in the command line is its identity;
    ``OPTION`` is named — its ``--spelling`` is. Typed as an enum so the emitted
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


class ArgvBinding(BaseModel):
    """How ONE operation parameter is spelled on the command line (#669).

    The missing half of a command's self-description: ``input`` says WHAT a
    command needs, this says HOW to write it as argv. Derived from the live
    Typer/Click parameter at emission time
    (:func:`gda.headless.command_argv_bindings`); the rationale, the boundaries
    and the case inventory are the ADR-0004 amendment (#669).

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
    :class:`~gda.execution.ExecutionKind` (serialized as the lowercase value
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
    are sourced from the single :func:`gda.execution.live_stack_constraints`
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
        command's static :class:`~gda.execution.ExecutionKind` (issue #230); it
        serializes to its lowercase string because ``ExecutionKind`` subclasses
        ``str``. ``constraints`` is the command's live-stack precondition or
        ``None`` (issue #233), computed by the caller from the single
        :func:`gda.execution.live_stack_constraints` authority. ``argv`` is the
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


class CommandManifestEntry(BaseModel):
    """One command's entry in the aggregate surface manifest (ADR-0012).

    The whole-surface generalisation of a single command's :class:`CommandSchema`:
    it carries the same model-derived ``input`` / ``output`` / ``error`` halves,
    plus the two facts gda-mcp needs to register a tool — ``name`` (the
    ``<group> <command>`` MCP mapping basis, ADR-0005, e.g. ``scene create``;
    bare for a meta command such as ``info``) and the command's ``description``
    (its help text, which flows into the MCP tool description).

    ``kind`` mirrors :class:`CommandSchema`'s: the entry's static execution
    channel as the typed :class:`~gda.execution.ExecutionKind` (serialized
    ``"headless"`` / ``"export"`` / ``"live"``), taken from the same descriptor
    source of truth so the aggregate and per-command forms agree (issue #230).
    Additive and ignored by gda-mcp (ADR-0012). Unlike :class:`CommandSchema`'s
    optional ``kind``, here it is **required**: every aggregate entry is a
    dispatchable command with a backing descriptor, so the self-described surface
    schema (``gda schema --schema``) guarantees the field and constrains it to
    the execution-kind enum — a consumer can rely on it always being present.

    ``constraints`` mirrors :class:`CommandSchema`'s: the entry's
    :class:`LiveStackConstraints`, or ``None`` for a command with no live-stack
    dependence (issue #233), from the same single
    :func:`gda.execution.live_stack_constraints` authority so the aggregate and
    per-command forms agree. Unlike :class:`CommandSchema`'s defaulted field, the
    **key is required** here (every dispatchable entry is computed from a backing
    descriptor, so the self-described surface schema guarantees the key is
    present) while its **value is nullable** (``null`` for non-live-stack
    commands) — a consumer can rely on the key always being there to read.

    ``argv`` mirrors :class:`CommandSchema`'s: how each of the command's
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
    :class:`CommandManifestEntry` per command in every group. An object (rather
    than a bare array) leaves room for top-level metadata later and gives the
    manifest its own schema, so ``gda schema --schema`` self-describes.
    """

    commands: list[CommandManifestEntry]


def normalize_path(path: str) -> str:
    """Normalize a path argument (issue #32; ADR-0015 moves it model-side).

    Engine-resolved virtual paths (``res://``, ``user://``, ``uid://``) pass
    through untouched — the engine resolves them against the project. A
    filesystem path gets ``~`` expanded so a literal ``~`` works without a shell.

    Lives here, not at the CLI layer, so the argv path and the ``--params-json``
    path normalize identically (ADR-0015): the model is the single home of
    normalization, applied wherever the model is constructed.

    Which paths are engine-virtual is ADR-0006's rule, owned by
    :func:`gda.project.is_engine_virtual_path` — the same test the project
    containment check reads, so the two cannot disagree about what ``res://``
    means.

    **Total: it never raises** (#699). ``Path.expanduser()`` raises ``RuntimeError``
    for a ``~unknownuser/…`` prefix it cannot resolve, which crashed every
    ``NormalizedPath`` consumer with a bare traceback. Such a path is passed through
    UNCHANGED instead. Two reasons it is swallowed rather than re-raised:

    - Normalization is a **convenience**, not a validity check — it saves the caller
      a shell. Whether a path is usable is decided by whoever consumes it (the
      operation that opens it, or a command's own path gate), and an unresolvable
      ``~user`` is simply a path that does not exist there.
    - Raising would not even fix the crash. The argv path constructs its params model
      DIRECTLY in the command body, so a ``ValueError`` becomes a pydantic
      ``ValidationError`` that escapes as a bare traceback anyway; only
      ``--params-json`` catches it. Staying total is what repairs BOTH input paths,
      for every consumer, without a per-command guard.
    """
    if is_engine_virtual_path(path):
        return path
    try:
        return str(Path(path).expanduser())
    except RuntimeError:
        return path


# The one reusable path-field type: a ``str`` whose value is run through
# ``normalize_path`` whenever the model is constructed (ADR-0015). Annotating a
# field with this is the single normalization mechanism shared by the argv and
# ``--params-json`` paths — no per-model ``@field_validator`` to maintain.
# ``AfterValidator`` (not Before): the value is validated as a ``str`` FIRST, so a
# wrong-typed ``--params-json`` value (e.g. ``{"path": 123}``) raises a
# ``ValidationError`` (→ structured ``invalid_params``) instead of ``normalize_path``
# hitting a ``TypeError`` on a non-string.
NormalizedPath = Annotated[str, AfterValidator(normalize_path)]


class RelayedLiveParams(BaseModel):
    """The base every RELAYED live command's params model inherits (#752).

    A live request that the daemon RELAYS is read by Godot's JSON parser, which
    cannot construct every binary64 value a caller can spell: a small-magnitude
    float arrives as ``0.0``, and a large integer as a different integer. That is
    a property of the daemon-to-harness leg — not of any one command, and not of
    ``ExecutionKind.LIVE`` either. Both proxies were tried and both were wrong:
    the rule started on ``GameCallParams``, which left every other relayed
    ingress open (#770 review), and then on every LIVE params model, which
    over-refused the ops the daemon answers ITSELF
    (``gda.daemon.server.DAEMON_SERVED_OPS`` — ``diag errors``, ``logger tail``,
    ``daemon wait-ready``). Those never reach Godot's parser: their params are
    consumed in Python, over a leg whose two ends are ``json.dumps`` and
    ``json.loads``, so refusing ``daemon wait-ready --timeout 5e-324`` told the
    caller a fact about a parser its number never meets.

    The params model is the boundary where the rule belongs: ADR-0015 makes it
    the ONE authority both the argv and ``--params-json`` paths build, so a single
    validator here refuses identically on both, and refuses a value BEFORE any
    daemon or engine session is involved — an input error stays an input error
    (a usage error on argv, ``invalid_params`` on ``--params-json``) instead of
    becoming a live-channel failure. :func:`~gda.live_numbers.find_unrepresentable`
    owns what "cannot cross" means; this class owns only where it is asked.

    The scan reads ``model_dump()`` rather than the field values, so a nested
    params model (an input-sequence event, a predicate's awaited value) is
    covered as plain JSON — and a relayed command whose recipe builds its wire
    dict from these same fields is covered with it. A relayed command that
    carries no number inherits this too: the guarantee is that no relayed params
    model can acquire a numeric field the wire silently changes, which a
    per-model opt-in could not give. ``tests/live/test_live_contract_guards.py``
    partitions the live Typer tree by ``DAEMON_SERVED_OPS`` and fails BOTH ways —
    a relayed descriptor that does not inherit this, and a daemon-served one that
    does.
    """

    @model_validator(mode="after")
    def _admit_live_wire_numbers(self) -> "RelayedLiveParams":
        for name, value in self.model_dump().items():
            refusal = find_unrepresentable(value, name)
            if refusal is not None:
                raise ValueError(refusal)
        return self


# The one read-side value projection every value gda emits goes through
# (ADR-0035): the shared field description for the dynamically-shaped `value`
# fields. The field itself stays `Any` — a value's shape is not statically
# knowable, a deliberate, bounded exception to ADR-0004's model-driven-output
# rule — so the stable parts are surfaced here and by the three named
# projection models (ReferenceProjection / TextureProjection /
# InlineValueProjection) below.
VALUE_PROJECTION_DESC = (
    "Rendered through the one recursive read-side value projection "
    "(ADR-0035): a scalar for a scalar type; a flat number list for a "
    "fixed-shape type (Vector2 → [x, y], Color → [r, g, b, a]); a JSON "
    "object for a Dictionary (keys stringified); a JSON array for an Array "
    "or packed array (elements re-projected). An Object value renders as a "
    "ReferenceProjection ({type, resource_path}) for a Resource with a "
    "res:// path, a TextureProjection ({type, width, height, object_string, "
    "digest}) for a PATH-LESS Texture2D (#666), an InlineValueProjection "
    "({type, …storage properties}) for a whitelisted path-less value Object "
    "(InputEvent subclasses), or its str() form for any other Object — "
    "branch on the presence of resource_path (reference) or object_string "
    "(texture)."
)

# The set-echo variant: the set commands echo the value they set through the
# SAME projection (they read it back off the subject and _jsonify it).
SET_ECHO_VALUE_DESC = (
    "The coerced value as JSON, in the same recursive value projection the "
    "corresponding get reports (ADR-0035)."
)

# node/resource set additionally have the ADR-0033 Object-typed set path;
# its echo flows through the same projection, so the assigned resource echoes
# as the reference projection a subsequent get reads back.
OBJECT_SET_ECHO_DESC = SET_ECHO_VALUE_DESC + (
    " Setting an Object-typed property by res:// path (ADR-0033) echoes the "
    "assigned resource as a ReferenceProjection ({type, resource_path}) — "
    "the same shape a subsequent get reads back."
)

# Stays in the shared core (ADR-0040 §4): FIVE groups report the SAME
# parent-directory side effect on their create results — ``scene``, ``script``,
# ``resource``, ``shader`` and ``theme`` — so the wording is a cross-command
# contract, not one group's constant. (``export run`` reports a DIFFERENT thing:
# the OUTPUT parent directories it made, so it keeps its own description.)
CREATED_DIRS_DESC = (
    "Parent directories created before saving, from outermost to innermost."
)


class ProjectRootedResult(BaseModel):
    """A result whose ``project_root`` gda supplies, not the engine (#658, #664).

    ``project_root`` is gda's own addition to an operation's answer: ADR-0006 keeps
    project resolution CLI-side and the engine is TOLD the project through
    ``--path``, so the ADR-0002 sentinel a result is parsed from carries only the
    fields ``operations.gd`` reports. The field is nonetheless declared REQUIRED and
    nullable on each result, so it appears in the published ``required`` list every
    consumer reads and an agent can read the key unconditionally — which would make
    that internal parse fail. The validator below supplies the absent key as
    ``null``, and each command's recipe stamps the resolved project immediately
    after.

    The leniency is inward-facing only: it never reaches the published contract, and
    anything that DOES carry the key (a recipe's ``model_copy``, a round-trip of an
    emitted result) passes through untouched.

    A base rather than a copied validator: ``script validate`` (#658) and ``scene
    validate`` (#664) need the identical rule for the identical reason, and a second
    hand-written copy is a second place for it to drift. It declares no fields, so a
    subclass's schema — field order included — is exactly what it was.
    """

    @model_validator(mode="before")
    @classmethod
    def _supply_absent_project_root(cls, data: Any) -> Any:
        if isinstance(data, dict) and "project_root" not in data:
            return {**data, "project_root": None}
        return data


class ReferenceProjection(BaseModel):
    """A Resource value named by type and ``res://`` path (ADR-0035).

    The read-side mirror of ADR-0033's write-side ``res://`` reference: a
    value that is a ``Resource`` with a ``res://`` ``resource_path`` projects
    to ``{type, resource_path}`` — never inlined, so a resource-valued read
    stays a small, bounded payload and read/write name an external resource
    the same way. Distinguished from :class:`InlineValueProjection` by the
    PRESENCE of ``resource_path`` (an inline projection excludes the Resource
    base bookkeeping, so it never carries one).
    """

    type: str = Field(
        description="The referenced resource's engine class (e.g. RectangleShape2D)."
    )
    resource_path: str = Field(
        description=(
            "The res:// path naming the resource; a sub-resource path "
            "(res://scene.tscn::id) counts as a reference too."
        )
    )


class InlineValueProjection(BaseModel):
    """A whitelisted path-less value Object projected inline (ADR-0035).

    A small path-less value ``Object`` on the projection whitelist
    (``InputEvent`` subclasses initially — e.g. the ``InputEventKey`` entries
    of an InputMap action) projects to ``{"type": <Class>, <its storage
    properties, each re-projected>}``. The ``Object``/``Resource`` base
    bookkeeping (``resource_path``, ``resource_name``,
    ``resource_local_to_scene``, ``script``) is excluded — so an inline
    projection never masquerades as a :class:`ReferenceProjection` — and so is
    the RESERVED key ``object_string`` (#666): only a
    :class:`TextureProjection` emits it, so an inline class's own storage
    property of that name is dropped rather than copied. The ``type``
    discriminator is assigned last, shadowing any storage property of
    that name. The storage properties vary per class, hence ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        description="The value Object's engine class (e.g. InputEventKey)."
    )


class TextureProjection(BaseModel):
    """A path-less ``Texture2D`` value named by class and dimensions (#666).

    The fourth projection kind (ADR-0035 amendment): a runtime-created texture
    (``ImageTexture.create_from_image()``) has no ``res://`` path, so the
    reference kind cannot name it and the string fallback's instance ID cannot
    say what it shows. Discriminated by the PRESENCE of ``object_string`` —
    the other object shapes never emit it, and this shape never emits
    ``resource_path`` (not even null), so the reference branch stays
    unambiguous. ``digest`` stays null unless the read opted in
    (``game get --texture-digest``): computing it needs
    ``Texture2D.get_image()``, a GPU-to-CPU readback on the live side.
    """

    type: str = Field(description="The texture's engine class (e.g. ImageTexture).")
    width: int = Field(description="The texture's width in pixels.")
    height: int = Field(description="The texture's height in pixels.")
    object_string: str = Field(
        description=(
            "The former str() form (class + instance ID), kept as secondary "
            "diagnostics; its presence is this kind's discriminator."
        )
    )
    digest: str | None = Field(
        description=(
            "'sha256:' + the hex digest over the image's dimensions, format, "
            "and raw bytes — always PRESENT, and null unless the read opted "
            "in (--texture-digest) or when the engine cannot read the image "
            "back (required-but-nullable: the producer always emits the key)."
        ),
    )


def projected_value_schema_extra(schema: dict[str, Any]) -> None:
    """Attach the named Object-projection shapes to a projected ``value`` field.

    A projected ``value`` stays ``Any`` — its shape is not statically knowable,
    the ADR-0035 bounded exception to ADR-0004 — so the stable projection
    shapes cannot ride along as the field's type (a union would materialize
    matching dicts as model instances and change the runtime payload).
    Attaching their schemas as the field's ``$defs`` keeps ReferenceProjection,
    TextureProjection, and InlineValueProjection named and consumable in every
    emitted command schema (``--schema`` / gda-mcp) instead of prose-only.
    """
    schema["$defs"] = {
        "ReferenceProjection": ReferenceProjection.model_json_schema(),
        "TextureProjection": TextureProjection.model_json_schema(),
        "InlineValueProjection": InlineValueProjection.model_json_schema(),
    }


# Stays in the shared core (ADR-0040 §4): three groups read the SAME typed
# property shape — ``node get``, ``resource get`` and the live ``game get`` — so
# it is a cross-command contract, not one group's model.
class NodeProperty(BaseModel):
    """One of a node's properties as ``gda node get`` reports it (issue #55).

    ``type`` is the property's declared Godot type name (``int``, ``Vector2``,
    ``Color``, …). ``value`` is the property's value in its recursive JSON
    value projection (ADR-0035) — left as arbitrary JSON so every Godot type
    is carried uniformly through one field: a scalar stays a scalar, a Vector2
    becomes ``[x, y]``, a Dictionary a JSON object, an Object a
    :class:`ReferenceProjection` / :class:`TextureProjection` /
    :class:`InlineValueProjection` / ``str()`` fallback.
    """

    name: str
    type: str = Field(
        description="The property's declared Godot type name (e.g. int, Vector2, Color)."
    )
    value: Any = Field(
        description="The property's value as JSON. " + VALUE_PROJECTION_DESC,
        json_schema_extra=projected_value_schema_extra,
    )


# Stays in the shared core (ADR-0040 §4): two groups read the SAME engine-version
# shape — the ``info`` meta command and ``project info`` — so it is a
# cross-command contract, not one group's model.
class EngineVersion(BaseModel):
    """The Godot engine version, as reported by ``Engine.get_version_info()``.

    This is the result model of ``gda info``, and the ``engine_version`` carried
    by ``gda project info``.
    """

    major: int
    minor: int
    patch: int
    hex: int
    status: str
    build: str
    hash: str
    string: str
    timestamp: int


# Stays in the shared core (ADR-0040 §4): TWO groups address a runtime node with
# the SAME description — ``game`` (get/rect/set) and ``perf`` (monitor) — so it is
# a cross-command contract, not one group's constant.
# The runtime node address: ABSOLUTE, as ``game tree`` reports it via the live
# tree's ``Node.get_path()``. This is the live counterpart of the node group's
# root-relative ``node`` param — the headless resolver rejects absolute paths,
# so the live layer addresses off the running SceneTree root instead (ADR-0019).
RUNTIME_NODE_DESC = (
    "Runtime node path as `game tree` reports it (absolute, e.g. /root/Main/Player)."
)


# Stays in the shared core (ADR-0040 §4): THREE groups bound a request against the
# SAME per-window ceiling — ``perf`` (monitor --frames), ``input`` (the sequence
# window) and ``screen`` (frames --frames) — so it is a cross-command contract, not
# one group's constant.
# The per-window frame ceiling a time-windowed live op may request (#223). A
# window collects exactly one sample per frame, so an unbounded N would block the
# one-shot RPC for an unbounded time; this is the same generous ceiling the gda
# harness enforces (``MAX_WINDOW_FRAMES`` in ``harness/gda_harness.gd``). Mirrored
# here so ``PerfMonitorParams.frames`` rejects an over-range value model-side
# (ADR-0015) — the model is the input source of truth for BOTH argv and
# ``--params-json``, so the bound is checked before a request ever reaches the
# harness, which therefore no longer clamps. The mirror is asserted by a harness-
# const test (``tests/cli/test_error_registry.py``).
MAX_WINDOW_FRAMES = 600
