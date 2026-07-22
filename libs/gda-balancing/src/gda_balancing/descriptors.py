"""The Command descriptor — the single registration seam (bADR-0011).

One frozen descriptor per command is the only way a command enters the
surface. Dispatch, ``--schema``, the future ``manifest``, and the conformance
harness are all projections of the registry; parallel registries are
prohibited, and the registered surface is enumerable without side effects.

The input/output *models* own field names, types, validation, defaults, and
serialization; the *descriptor* owns argv presentation: every input-model
field binds as a kebab-case ``--<field-name>`` option, except that the
descriptor may designate at most one field as the positional argument — the
designation replaces that field's option binding (bADR-0011's binding law).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from gda_balancing.envelope import RefusalReport
from gda_balancing.schema2.diagnostics import Schema2RefusalReport

# Reserved by bADR-0007 for Phase 2; the conformance harness asserts no
# registered command occupies them, and dispatch resolves them as unknown.
RESERVED_GROUPS = frozenset({"evaluation", "tuning"})
RESERVED_META: frozenset[str] = frozenset()


class ArtifactSpec(BaseModel):
    """The one normative receipt member (bADR-0009): the resolved sink path and
    the byte count written there. Closed and frozen — the receipt shape is a
    published contract, not an open bag."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    bytes: int


class ArtifactReceipt(BaseModel):
    """The stdout receipt an ``--out`` invocation emits in place of the artifact
    body (bADR-0009): ``artifact: {path, bytes}`` and nothing else. Present in a
    result exactly when ``--out`` was used, forbidden otherwise — so every
    artifact-sink command's output model is ``RootModel[<Body> | ArtifactReceipt]``
    (see :attr:`CommandDescriptor.artifact_sink`), letting the dispatch tail
    construct the receipt as the declared output type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: ArtifactSpec


@dataclass(frozen=True)
class ConformanceFixtures:
    """Per-command cases the conformance harness drives (bADR-0011).

    ``valid_args`` is the argument *tail* of one valid invocation — the
    command path itself is derived from the descriptor by every harness row,
    so fixture and identity cannot drift apart.

    ``valid_document`` and ``refusing_document`` are the Design-document
    fixtures for a document-taking command, given as **JSON document content,
    never a file path**: the harness materializes each to a tmp file and
    appends that path as the positional argument (a committed ``.json`` file
    would both be cwd-dependent and trip the isolation gate's per-game-config
    scan). ``refusing_document`` — a document that provokes a *stable* funnel
    refusal — is required for a document-taking command (bADR-0011's refusal
    row); a command that takes no document leaves both ``None``.
    """

    valid_args: tuple[str, ...] = ()
    valid_document: str | None = None
    refusing_document: str | None = None


@dataclass(frozen=True)
class CommandDescriptor:
    """Everything the surface needs to run, describe, and test one command."""

    group: str | None
    command: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    # Pure: takes the bound input model and returns the output model on
    # success or a typed-refusal report (bADR-0011's two normative outcomes;
    # #504's funnel is the first refusal producer); never prints, never
    # exits, never sees a usage error. An unexpected exception here is the
    # sole path to `internal` / exit 4. Typed `...` because each command's
    # handler takes its own concrete input model (contravariance).
    handler: Callable[..., BaseModel | RefusalReport | Schema2RefusalReport]
    fixtures: ConformanceFixtures
    positional_field: str | None = None
    # Execution markings (bADR-0010/0011); the harness's per-marking rows key
    # off them.
    stochastic: bool = field(default=False)
    # `artifact_sink` marks a command that emits a canonical artifact and so
    # accepts `--out <path>` (bADR-0009): the artifact body goes to the sink and
    # stdout carries an `ArtifactReceipt` instead. Only such commands accept
    # `--out`; every other command rejects it as an unknown argument. Contract:
    # an artifact-sink command's `output_model` MUST be
    # `RootModel[<Body> | ArtifactReceipt]`, so the dispatch tail can construct
    # the receipt as the declared output type.
    artifact_sink: bool = field(default=False)
    # The current registry temporarily contains historical 1.x commands while
    # Schema 2.0 lands in vertical slices.  Only descriptors marked ``2`` are
    # projected into the 2.x Surface manifest.
    schema_major: int = field(default=1)
    structured_params: bool = field(default=False)
    refusal_stages: tuple[str, ...] = field(default=())
    # A 2.x descriptor may own a closed schema that is more precise than a
    # dynamic RootModel. Dispatch validates its result against this same
    # callable used by --schema and manifest.
    success_schema: Callable[[], dict[str, object]] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.group in RESERVED_GROUPS or (
            self.group is None and self.command in RESERVED_GROUPS | RESERVED_META
        ):
            raise ValueError(f"reserved name: {self.group or self.command!r}")
        if self.schema_major not in (1, 2):
            raise ValueError(
                f"unsupported descriptor schema major: {self.schema_major}"
            )
        if self.structured_params and self.schema_major != 2:
            raise ValueError("structured params are a Schema 2.x descriptor contract")
        if (
            self.positional_field is not None
            and self.positional_field not in self.input_model.model_fields
        ):
            raise ValueError(
                f"positional designation {self.positional_field!r} names no "
                f"{self.input_model.__name__} field"
            )


def build_registry(*descriptors: CommandDescriptor) -> tuple[CommandDescriptor, ...]:
    """Assemble the registry, enforcing single-authority command identity:
    a duplicate ``(group, command)`` path is a registration error, never a
    silently-shadowed dispatch."""
    seen: set[tuple[str | None, str]] = set()
    for descriptor in descriptors:
        path = (descriptor.group, descriptor.command)
        if path in seen:
            joined = " ".join(p for p in path if p is not None)
            raise ValueError(f"duplicate command registration: {joined}")
        seen.add(path)
    return tuple(descriptors)


def option_bindings(descriptor: CommandDescriptor) -> dict[str, str]:
    """The binding-law projection: ``--kebab-case`` option name → model field.

    The positional designation replaces that field's option binding — the
    field is positional-only, never also ``--<field-name>``.
    """
    return {
        "--" + name.replace("_", "-"): name
        for name in descriptor.input_model.model_fields
        if name != descriptor.positional_field
    }
