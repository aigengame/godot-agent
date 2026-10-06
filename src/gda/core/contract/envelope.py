"""The `Error envelope` models (ADR-0004).

Split out of the shared contract core by ADR-0045 §2: the one failure contract
every command shares — the category, the environment probe, the termination phase,
the typed evidence with its placement projection, the error and its three envelopes,
and the live stack constraints.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from gda.core.engine.script_errors import ScriptError
from gda.core.engine.user_data import UserDataReport


# The category→code decision tree is gda.core.failure.classify.classify_run.
class ErrorCategory(str, Enum):
    """The coarse buckets a ``gda`` operation can fail into (issue #3).

    This is the coarse axis; each category fans out to one or more finer,
    stable ``GdaError.code`` values (e.g. ``environment`` → ``binary_not_found`` /
    ``launch_timeout``; ``operation`` → ``operation_failed`` / ``engine_crashed``).

    ``environment`` covers everything before the operation produces a result — the
    binary not launching, or launching and hanging past the timeout. ``version`` is
    a launched engine below the supported minimum (ADR-0003). ``operation`` is a
    launched engine that failed to deliver a result (the operation reported an
    error, or the engine crashed). ``parse`` is a violation of the structured-output
    contract (ADR-0002): a missing/malformed sentinel or a wrong-shape payload.
    ``live`` is a Phase-2 live operation failing against ``gda-daemon`` / the engine
    session — no running daemon, a lost session, or a live timeout (ADR-0017,
    ADR-0021). ``usage`` is the one bucket that precedes all of them: gda could not
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
    # The value is sys.platform.
    platform: str = Field(
        description="The host platform identifier the probe ran on, e.g. darwin or linux."
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
            "that status (script run --strict, export smoke --strict). Not the "
            "gda process exit code."
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
            "the verdict is 'code', never an entry here — though under a --strict "
            "gate ('script_failed', 'smoke_failed') a 'shutdown_leak' entry can "
            "be the trigger the caller opted into."
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
    # The two export-templates directories a `--user-data-root` redirect puts at
    # odds (#840). Godot reads the templates from the data directory the redirect
    # relocates, so `export_templates_missing` has two shapes that need different
    # remedies, and the message alone cannot be branched on: `templates_root_host`
    # is present exactly when the templates ARE installed somewhere this run could
    # not see, and absent when they are genuinely missing.
    templates_root_checked: str | None = Field(
        default=None,
        description=(
            "The export-templates directory this run checked — the one the "
            "engine's data directory resolved to, which --user-data-root moves."
        ),
    )
    templates_root_host: str | None = Field(
        default=None,
        description=(
            "The host's export-templates directory, when it holds the templates a "
            "--user-data-root redirect hid from this run. Set only then: its "
            "absence means the templates are missing on the host too."
        ),
    )
    # The two spellings of a `path_case_mismatch` refusal (#845): the address the
    # caller asked for and the one the project actually stores. Both are already in
    # hand on the failure path (the authority reads the directory entries to reach the
    # verdict), neither is recoverable from the envelope without reading the message,
    # and the stored one is what the caller re-issues with — which is why it rides
    # here rather than as a `hint`, whose contract is the curated near-miss table.
    requested_path: str | None = Field(
        default=None,
        description=(
            "The res:// address as the caller spelled it, on a refusal about the "
            "spelling itself."
        ),
    )
    stored_path: str | None = Field(
        default=None,
        description=(
            "The res:// address as the project stores it — the corrected spelling "
            "to re-issue with, on a path_case_mismatch."
        ),
    )
    # Where the launch that produced this failure put Godot's user data (#862) — the
    # `User-data placement` #850 published on the SUCCESS result, now on the failure
    # half of the same channel. Three of that channel's builders set them and nothing
    # else does — the three ADR-0004's #862 note names, which are the ones that
    # already carried evidence: a persistence-bearing run that fails because `user://`
    # was not writable reads as a game regression until the envelope says which
    # directory the engine actually resolved, and on a timeout the log is where the
    # caller looks next.
    #
    # The presence rules are the success result's, with ONE difference that the
    # omitted-never-null rule of this object decides: `engine_data_path` is
    # required-but-nullable there and OMITTED here when the platform's own data
    # variable is unset.
    #
    # The three names are `PLACEMENT_FIELD_NAMES` and the projection that fills them
    # is `placement_fields`, both below this class: the launch primitive keeps the
    # raw paths and their lifetimes, this core owns what they are called on the wire.
    engine_data_path: str | None = Field(
        default=None,
        description=(
            "The directory the engine resolved 'user://' beneath for the run this "
            "failure reports — under 'user_data_root' when one was given. Omitted "
            "when the platform's own data variable is unset, which the success "
            "result reports as null instead."
        ),
    )
    user_data_root: str | None = Field(
        default=None,
        description=(
            "The --user-data-root / $GDA_USER_DATA_ROOT directory this run was "
            "placed under. Omitted when none was given — gda then redirects only "
            "the engine log."
        ),
    )
    log_file: str | None = Field(
        default=None,
        description=(
            "The engine log of this run, reported only under a --user-data-root: "
            "the one case in which it outlives the launch. On a run gda ended, it is "
            "the file to read next. By default the log is a private temporary file "
            "gda removes."
        ),
    )
    # The classes the engine's GDScript analyzer reported it could not resolve, read
    # from the run's own error lines by the one CLI-side seam (#1073,
    # `gda.core.failure.classify.class_resolution_remedy`). Set only on the channels
    # whose engine reads the class index without running the import pass — the sentinel
    # ops and `script run` — because there a missing or out-of-date index is a cause the
    # caller can remove with `gda project scan` before the same call. The code stays the
    # verdict; the names say which class the remedy is about.
    unresolved_classes: list[str] | None = Field(
        default=None,
        description=(
            "The class names the engine could not resolve when it compiled a "
            "script for this call, in the order it reported them. Present only "
            "when the run reported one: run `gda project scan` and retry, because "
            "the engine finds a project class_name only through the class index "
            "that scan writes."
        ),
    )

    @field_serializer("script_errors")
    def _keep_the_published_script_error_shape(
        self, errors: list[ScriptError] | None
    ) -> list[dict[str, Any]] | None:
        """Serialize the records with their FULL key set, nulls included (#687 review).

        The failure envelope is emitted with ``exclude_none``
        (:func:`gda.surface.descriptor.emit_failure`), which recurses. Without this, a
        null ``path`` / ``line`` would be dropped from the nested records and the SAME
        script error would carry different keys depending on which half of the contract
        a caller read it from — four keys on ``script run``'s success ``diagnostics``,
        two or three here — while both halves are described by one published
        ``ScriptError`` schema whose ``path`` / ``line`` say "or null".

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


#: The public key names a `User-data placement` projects to, in the order
#: :class:`FailureEvidence` above and ``script run``'s result model declare them.
#: ONE authority for the trio: :func:`placement_fields` builds the projection, and
#: the two boundary guards that hold the disclosure to that one channel read these
#: names rather than each keeping a hand-written copy (#862).
PLACEMENT_FIELD_NAMES = ("engine_data_path", "user_data_root", "log_file")


def placement_fields(report: "UserDataReport | None") -> dict[str, str]:
    """A launch's `User-data placement` as the public keys, PRESENT facts only (#862).

    The single projection of the launch primitive's raw record into the strings a
    result or an `Error envelope` publishes. It lives HERE, beside the
    :class:`FailureEvidence` fields that declare the three names, rather than on the
    record itself: :class:`~gda.core.engine.user_data.UserDataReport` owns which paths are facts and
    how long each one lives, and this contract core owns what they are CALLED on the
    wire (ADR-0040 §5). Both halves of ``gda script run`` read it — the success result
    for its three flattened keys, and the three failure builders ADR-0004's #862 note
    names for `Failure evidence` — so the two halves cannot spell or omit a placement
    differently.

    A key is ABSENT whenever its path is ``None``, so the caller asks for what it
    wants and gets the fact or nothing. That one shape serves the two different null
    contracts without either side re-deciding them: the success model declares
    ``engine_data_path`` with a ``None`` default, so a missing key still publishes
    ``null`` there, while every field of `Failure evidence` is omitted rather than
    nulled, so a missing key publishes nothing.

    A ``None`` report projects to no keys at all. That is a hand-built run at a test
    seam — every real launch attaches a report — or a launch REFUSED before a
    placement existed (``user_data_unwritable``, whose own diagnostics name what was
    attempted).
    """
    if report is None:
        return {}
    return {
        name: str(value)
        for name, value in zip(
            PLACEMENT_FIELD_NAMES,
            (report.data_path, report.root, report.log_file),
            strict=True,
        )
        if value is not None
    }


# The nested-model rule is FailureEvidence._keep_the_published_script_error_shape.
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
    the same on both halves of the contract.
    """

    category: ErrorCategory
    code: str
    message: str
    diagnostics: str = ""
    # OMITTED — not ``null`` — from every failure that sets none: the emit path
    # (:func:`gda.surface.descriptor.emit_failure`) serializes with ``exclude_none``, so
    # each other code's envelope JSON stays byte-identical to the pre-amendment
    # contract. Deliberately the minimal axis — WHICH host call decided — never the
    # typed EVIDENCE of a failure (parsed script errors, exit statuses), which #687
    # decided separately and carries in ``evidence`` below (ADR-0004 amendments,
    # #667/#687).
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
    # anything. Set only where gda RECOGNIZES the mistake (the curated near-miss table,
    # gda.surface.hints) — never a difflib guess, which can name a different operation
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


# The one authority for both facets is gda.core.engine.execution.live_stack_constraints.
class LiveStackConstraints(BaseModel):
    """The platform / Godot-version precondition a live-stack command needs (issue #233).

    A structured, machine-discoverable form of the constraint that ``gda``'s
    daemon/live stack carries — macOS/Linux only (Unix domain sockets) and, where
    a command launches/uses the engine, Godot 4.6+ (ADR-0021) — replacing the
    prose that used to live only in ``--help`` text and the manifest description.
    Present (non-``null``) only on commands that depend on the live stack: the
    LIVE-channel domain commands (``game …``) and the ``daemon`` lifecycle group;
    every other command's ``constraints`` is ``null``.

    Both facets come from one authority, so the structured field and the
    help/manifest prose cannot drift:

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
