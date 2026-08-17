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
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.interfaces.cli.envelope import USAGE_CODES
from gda_balancing.domain.authority.admission import SCHEMA2_REFUSAL_STAGES
from gda_balancing.domain.diagnostics import Schema2RefusalReport

# Reserved by bADR-0007 for Phase 2; the conformance harness asserts no
# registered command occupies them, and dispatch resolves them as unknown.
RESERVED_GROUPS = frozenset({"evaluation", "tuning"})
RESERVED_META: frozenset[str] = frozenset()
_SCHEMA2_REFUSAL_STAGES = frozenset(SCHEMA2_REFUSAL_STAGES)


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

    ``refusing_args`` is the complete argument tail of one invocation that
    reaches a stable domain refusal without requiring a document fixture.
    Artifact-set sinks and invocation keys remain harness-projected.

    ``valid_document`` and ``refusing_document`` are the Design-document
    fixtures for a document-taking command, given as **JSON document content,
    never a file path**: the harness materializes each to a tmp file and
    appends that path as the positional argument (a committed ``.json`` file
    would both be cwd-dependent and trip the isolation gate's per-game-config
    scan). A stateful command may instead provide ``prepare_valid_document``;
    the public prerequisite path it drives is then the only valid-document
    authority. ``refusing_document`` — a document that provokes a *stable*
    funnel refusal — is required for a document-taking command (bADR-0011's
    refusal row); a command that takes no document leaves both sources
    ``None``.
    """

    valid_args: tuple[str, ...] = ()
    refusing_args: tuple[str, ...] = ()
    valid_document: str | None = None
    refusing_document: str | None = None
    # Stateful artifact consumers may prepare their valid document by running
    # declared public prerequisites inside the isolated conformance store.
    prepare_valid_document: Callable[[Path, int], str] | None = None
    prepare_verdict_document: Callable[[Path, int], str] | None = None
    # A foreground descriptor supplies one valid readiness value for the
    # registry-walking lifecycle row. The real process/server path remains an
    # end-to-end test; this fixture proves descriptor dispatch and projection.
    foreground_readiness: dict[str, object] | None = None

    @property
    def has_valid_document(self) -> bool:
        """Whether the harness owns one static or prepared valid document."""
        return (
            self.valid_document is not None or self.prepare_valid_document is not None
        )


@dataclass(frozen=True)
class RefusalDetailSpec:
    """The one closed, stage-specific detail field admitted in 2.x."""

    stage: Literal["migration", "runtime"]
    field_name: Literal["migration_report", "terminal_audit"]
    schema: Callable[[], dict[str, object]]
    required: bool = True

    def __post_init__(self) -> None:
        if (self.stage, self.field_name) not in {
            ("migration", "migration_report"),
            ("runtime", "terminal_audit"),
        }:
            raise ValueError(
                "migration-report and terminal-audit are the only Schema 2.x "
                "refusal details and each belongs to its declared stage"
            )


@dataclass(frozen=True)
class RefusalVariantSpec:
    """One descriptor-owned variant within a shared refusal stage."""

    stage: Literal["migration", "runtime"]
    id: str
    required_details: tuple[Literal["migration_report", "terminal_audit"], ...] = ()
    forbidden_details: tuple[Literal["migration_report", "terminal_audit"], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("refusal variant id must be non-empty")
        if len(self.required_details) != len(set(self.required_details)) or len(
            self.forbidden_details
        ) != len(set(self.forbidden_details)):
            raise ValueError("refusal variant detail members must be unique")
        if set(self.required_details) & set(self.forbidden_details):
            raise ValueError("one refusal detail cannot be required and forbidden")


@dataclass(frozen=True)
class RefusalArtifactSetSpec:
    """One stage-owned artifact set published before a typed refusal."""

    stage: Literal["runtime"]
    members: tuple[ArtifactSetMemberSpec, ...]
    variant: str | None = None

    def __post_init__(self) -> None:
        names = [member.logical_name for member in self.members]
        if (
            not self.members
            or len(names) != len(set(names))
            or sum(member.role == "primary" for member in self.members) != 1
        ):
            raise ValueError(
                "a refusal artifact set requires unique names and one primary"
            )


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
    handler: Callable[..., BaseModel | Schema2RefusalReport] | None
    fixtures: ConformanceFixtures
    # A completed negative judgment is a third typed handler result. It is
    # emitted on stdout with exit 1 and remains distinct from refusal.
    verdict_model: type[BaseModel] | None = field(default=None)
    positional_field: str | None = None
    # Optional input field selecting canonical or indented JSON presentation.
    # It changes whitespace only; handlers still return the same typed value.
    json_presentation_field: str | None = field(default=None)
    # Execution markings (bADR-0010/0011); the harness's per-marking rows key
    # off them.
    stochastic: bool = field(default=False)
    execution_lifecycle: Literal["one-shot", "foreground-service"] = field(
        default="one-shot"
    )
    # A foreground runner receives the bound input, a dispatch-owned readiness
    # emitter, and stderr for operational logs. The emitter validates and flushes
    # the descriptor's exact output model; the runner returns only after shutdown.
    foreground_runner: Callable[..., int] | None = field(default=None)
    # `artifact_sink` marks a command that emits a canonical artifact and so
    # accepts `--out <path>` (bADR-0009): the artifact body goes to the sink and
    # stdout carries an `ArtifactReceipt` instead. Only such commands accept
    # `--out`; every other command rejects it as an unknown argument. Contract:
    # an artifact-sink command's `output_model` MUST be
    # `RootModel[<Body> | ArtifactReceipt]`, so the dispatch tail can construct
    # the receipt as the declared output type.
    artifact_sink: bool = field(default=False)
    # A Schema 2.x multi-artifact producer owns publication in its handler and
    # returns the committed set receipt. This is distinct from the single-file
    # ``artifact_sink`` dispatch tail.
    artifact_set: tuple[ArtifactSetMemberSpec, ...] = field(default=())
    verdict_artifact_set: tuple[ArtifactSetMemberSpec, ...] = field(default=())
    # The active surface is Standard Schema 2.x. Standard Schema 1.x is
    # consumed only by the Model migration application flow.
    schema_major: Literal[2] = field(default=2)
    structured_params: bool = field(default=False)
    # Exact per-command error authority for Schema 2.x.  The catalog is a
    # reverse-conformance projection of Kernel/LDB Diagnostics; dispatch and
    # --schema both consume it, so an undeclared stage/code cannot leak.
    refusal_catalog: tuple[tuple[str, str], ...] = field(default=())
    # A catalog that depends on admitted authority may be resolved at the first
    # refusal/schema projection. The owning descriptor module need not admit the
    # authority at import; static descriptors continue to use the field above.
    refusal_catalog_provider: Callable[[], tuple[tuple[str, str], ...]] | None = field(
        default=None
    )
    # Stage-specific refusal fields remain closed and descriptor-owned. Their
    # schemas are shared by dispatch validation, --schema, manifest, and
    # descriptor identity; handlers cannot add an ambient details bag.
    refusal_details: tuple[RefusalDetailSpec, ...] = field(default=())
    refusal_variants: tuple[RefusalVariantSpec, ...] = field(default=())
    refusal_artifact_sets: tuple[RefusalArtifactSetSpec, ...] = field(default=())
    usage_codes: tuple[str, ...] = field(default=())
    # A 2.x descriptor may own a closed schema that is more precise than a
    # dynamic RootModel. Dispatch validates its result against this same
    # callable used by --schema and manifest.
    success_schema: Callable[[], dict[str, object]] | None = field(default=None)
    verdict_schema: Callable[[], dict[str, object]] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.group in RESERVED_GROUPS or (
            self.group is None and self.command in RESERVED_GROUPS | RESERVED_META
        ):
            raise ValueError(f"reserved name: {self.group or self.command!r}")
        if self.schema_major != 2:
            raise ValueError("the active descriptor surface is Standard Schema 2.x")
        if self.execution_lifecycle == "one-shot":
            if self.handler is None or self.foreground_runner is not None:
                raise ValueError("one-shot descriptor requires only its handler")
        elif self.handler is not None or self.foreground_runner is None:
            raise ValueError(
                "foreground-service descriptor requires only its foreground runner"
            )
        if (self.fixtures.foreground_readiness is not None) != (
            self.execution_lifecycle == "foreground-service"
        ):
            raise ValueError(
                "foreground readiness fixture must match the descriptor lifecycle"
            )
        if (self.artifact_set or self.verdict_artifact_set) and self.artifact_sink:
            raise ValueError(
                "one descriptor cannot use both artifact publication paths"
            )
        for outcome, members in (
            ("success", self.artifact_set),
            ("verdict", self.verdict_artifact_set),
        ):
            if not members:
                continue
            names = [member.logical_name for member in members]
            if len(names) != len(set(names)):
                raise ValueError(f"{outcome} artifact-set logical names must be unique")
            if sum(member.role == "primary" for member in members) != 1:
                raise ValueError(
                    f"{outcome} artifact set must declare exactly one primary member"
                )
        if self.verdict_model is None and (
            self.verdict_artifact_set or self.verdict_schema is not None
        ):
            raise ValueError("verdict contracts require a declared verdict model")
        if self.refusal_catalog and self.refusal_catalog_provider is not None:
            raise ValueError("refusal catalog has both static and deferred sources")
        refusal_detail_keys = [
            (detail.stage, detail.field_name) for detail in self.refusal_details
        ]
        if len(refusal_detail_keys) != len(set(refusal_detail_keys)):
            raise ValueError("duplicate Schema 2.x refusal-detail field")
        refusal_variant_keys = [
            (variant.stage, variant.id) for variant in self.refusal_variants
        ]
        if len(refusal_variant_keys) != len(set(refusal_variant_keys)):
            raise ValueError("duplicate Schema 2.x refusal variant")
        for variant in self.refusal_variants:
            referenced = set(variant.required_details) | set(variant.forbidden_details)
            if not {(variant.stage, detail) for detail in referenced} <= set(
                refusal_detail_keys
            ):
                raise ValueError("refusal variant references an undeclared detail")
            if any(
                detail.required and detail.field_name in variant.forbidden_details
                for detail in self.refusal_details
                if detail.stage == variant.stage
            ):
                raise ValueError("refusal variant forbids a globally required detail")
        for stage in {variant.stage for variant in self.refusal_variants}:
            variants = [
                variant for variant in self.refusal_variants if variant.stage == stage
            ]
            for index, left in enumerate(variants):
                for right in variants[index + 1 :]:
                    if not (
                        set(left.required_details) & set(right.forbidden_details)
                        or set(right.required_details) & set(left.forbidden_details)
                    ):
                        raise ValueError(
                            "refusal variants in one stage must be structurally disjoint"
                        )
        refusal_set_stages = [item.stage for item in self.refusal_artifact_sets]
        if len(refusal_set_stages) != len(set(refusal_set_stages)):
            raise ValueError("duplicate refusal artifact-set stage")
        if any(
            (item.stage, "terminal_audit") not in refusal_detail_keys
            for item in self.refusal_artifact_sets
        ):
            raise ValueError("refusal artifact set requires its typed receipt detail")
        for item in self.refusal_artifact_sets:
            stage_variants = [
                variant
                for variant in self.refusal_variants
                if variant.stage == item.stage
            ]
            if stage_variants and (
                item.variant is None
                or (item.stage, item.variant) not in set(refusal_variant_keys)
            ):
                raise ValueError(
                    "refusal artifact set requires one reachable stage variant"
                )
        if any(
            item.variant is not None
            and not any(
                variant.stage == item.stage
                and variant.id == item.variant
                and "terminal_audit" in variant.required_details
                for variant in self.refusal_variants
            )
            for item in self.refusal_artifact_sets
        ):
            raise ValueError(
                "refusal artifact set variant must require its terminal audit"
            )
        if not set(self.usage_codes) <= USAGE_CODES:
            raise ValueError("unknown Schema 2.x usage code")
        if self.refusal_catalog_provider is None:
            self._validate_refusal_catalog(self.refusal_catalog)
        if (
            self.positional_field is not None
            and self.positional_field not in self.input_model.model_fields
        ):
            raise ValueError(
                f"positional designation {self.positional_field!r} names no "
                f"{self.input_model.__name__} field"
            )
        if (
            self.json_presentation_field is not None
            and self.json_presentation_field not in self.input_model.model_fields
        ):
            raise ValueError(
                f"JSON presentation field {self.json_presentation_field!r} names no "
                f"{self.input_model.__name__} field"
            )

    @property
    def refusal_stages(self) -> tuple[str, ...]:
        return tuple(sorted({stage for _, stage in self.resolved_refusal_catalog()}))

    def resolved_refusal_catalog(self) -> tuple[tuple[str, str], ...]:
        """Resolve and validate the descriptor's exact refusal catalog."""
        catalog = (
            self.refusal_catalog_provider()
            if self.refusal_catalog_provider is not None
            else self.refusal_catalog
        )
        self._validate_refusal_catalog(catalog)
        return catalog

    def _validate_refusal_catalog(self, catalog: tuple[tuple[str, str], ...]) -> None:
        if not isinstance(catalog, tuple) or len(catalog) != len(set(catalog)):
            raise ValueError("duplicate Schema 2.x refusal catalog entry")
        if any(
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not entry[0]
            or entry[1] not in _SCHEMA2_REFUSAL_STAGES
            for entry in catalog
        ):
            raise ValueError("invalid Schema 2.x refusal catalog entry")
        stages = {stage for _, stage in catalog}
        if any(detail.stage not in stages for detail in self.refusal_details):
            raise ValueError("refusal detail belongs to an unreachable stage")
        if any(variant.stage not in stages for variant in self.refusal_variants):
            raise ValueError("refusal variant belongs to an unreachable stage")
        if any(item.stage not in stages for item in self.refusal_artifact_sets):
            raise ValueError("refusal artifact set belongs to an unreachable stage")


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
