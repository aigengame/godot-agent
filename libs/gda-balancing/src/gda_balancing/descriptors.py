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

from pydantic import BaseModel

# Reserved by bADR-0007 for Phase 2; the conformance harness asserts no
# registered command occupies them, and dispatch resolves them as unknown.
RESERVED_GROUPS = frozenset({"evaluation", "tuning"})
RESERVED_META = frozenset({"manifest"})


@dataclass(frozen=True)
class ConformanceFixtures:
    """Per-command cases the conformance harness drives (bADR-0011).

    ``valid_argv`` is a full argv for one valid invocation. ``refusing_input``
    is required for document-taking commands only — none exist in v1 (#504).
    """

    valid_argv: tuple[str, ...]
    refusing_input: str | None = None


@dataclass(frozen=True)
class CommandDescriptor:
    """Everything the surface needs to run, describe, and test one command."""

    group: str | None
    command: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    # Pure: takes the bound input model and returns the output model on
    # success (v1) or a typed-refusal report (#504); never prints, never
    # exits, never sees a usage error. An unexpected exception here is the
    # sole path to `internal` / exit 4. Typed `...` because each command's
    # handler takes its own concrete input model (contravariance).
    handler: Callable[..., BaseModel]
    fixtures: ConformanceFixtures
    positional_field: str | None = None
    # Execution markings — today exactly one (bADR-0010/0011). No v1 command
    # sets it; the harness's seed row keys off it.
    stochastic: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.group in RESERVED_GROUPS or (
            self.group is None and self.command in RESERVED_GROUPS | RESERVED_META
        ):
            raise ValueError(f"reserved name: {self.group or self.command!r}")
        if (
            self.positional_field is not None
            and self.positional_field not in self.input_model.model_fields
        ):
            raise ValueError(
                f"positional designation {self.positional_field!r} names no "
                f"{self.input_model.__name__} field"
            )


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
