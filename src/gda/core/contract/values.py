"""Typed result models (ADR-0004).

Each command's result is carried by a Pydantic model rather than an ad-hoc
dict, so the same model both serializes the ``--json`` output now and produces
the ``--schema`` document later (``model_json_schema()``) without
hand-maintaining the contract twice.
"""

from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from gda.core.contract.live_numbers import find_unrepresentable
from gda.core.project.paths import expand_user_or_none, is_engine_virtual_path


def normalize_path(path: str) -> str:
    """Normalize a path argument (issue #32; ADR-0015 moves it model-side).

    Engine-resolved virtual paths (``res://``, ``user://``, ``uid://``) pass
    through untouched — the engine resolves them against the project. A
    filesystem path gets ``~`` expanded so a literal ``~`` works without a shell.

    Lives here, not at the CLI layer, so the argv path and the ``--params-json``
    path normalize identically (ADR-0015): the model is the single home of
    normalization, applied wherever the model is constructed.

    Which paths are engine-virtual is ADR-0006's rule, owned by
    :func:`gda.core.project.paths.is_engine_virtual_path` — the same test the project
    containment check reads, so the two cannot disagree about what ``res://``
    means.

    **Total: it never raises** (#699). ``Path.expanduser()`` raises ``RuntimeError``
    for a ``~unknownuser/…`` prefix it cannot resolve, which crashed every
    ``NormalizedPath`` consumer with a bare traceback. Such a path is passed through
    UNCHANGED instead. The decision is :func:`gda.core.project.paths.expand_user_or_none`'s,
    the one in-process statement of the rule (#988); this function keeps only its
    own answer — the caller's raw string — beside the virtual-path pass-through
    above. Two reasons it is swallowed rather than re-raised:

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
    expanded = expand_user_or_none(Path(path))
    return path if expanded is None else str(expanded)


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

    The params model is the boundary where the rule belongs: ADR-0015 makes it the ONE
    authority both the argv and ``--params-json`` paths build, so a single validator
    here refuses identically on both, and refuses a value BEFORE any daemon or engine
    session is involved — an input error stays an input error (a usage error on argv,
    ``invalid_params`` on ``--params-json``) instead of becoming a live-channel failure.
    :func:`~gda.core.contract.live_numbers.find_unrepresentable` owns what "cannot
    cross" means; this class owns only where it is asked.

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

# The stale-entry field ``script validate`` and ``scene validate`` share (#1073).
# One model for both, because the index is a project-level fact and one call
# resolves one project (ADR-0006); the predicate that fills it has one home, the
# engine-side class index module.
STALE_CLASS_ENTRIES_DESC = (
    "Every entry of the engine's class index whose script, loaded in this process "
    "and compiled, declares another class_name now (or none): a class_name renamed "
    "or removed with no scan. The scripts checked are the ones the validation "
    "compiled and their dependencies, and the project's autoloads, so a stale entry "
    "an autoload reaches makes every validate verdict invalid. Not empty makes "
    "'valid' false. The next import pass (`gda project scan`, `gda resource "
    "import`, `gda export run` or the editor) rewrites the index, and code that "
    "uses the old name then fails to compile: run `gda project scan` and validate "
    "again. Empty when no loaded script is a stale entry."
)


class StaleClassEntry(BaseModel):
    """One stale class index entry (#1073): the class, its path, the name declared now."""

    name: str = Field(description="The class_name the index entry holds.")
    path: str = Field(description="The res:// path of the entry's script.")
    declared_name: str = Field(
        description=(
            "The class_name the compiled script declares now; empty when it "
            "declares none."
        )
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
    the same way. Distinguished from ``InlineValueProjection`` by the
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
    projection never masquerades as a ``ReferenceProjection`` — and so is
    the RESERVED key ``object_string`` (#666): only a
    ``TextureProjection`` emits it, so an inline class's own storage
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
    ``ReferenceProjection`` / ``TextureProjection`` /
    ``InlineValueProjection`` / ``str()`` fallback.
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
